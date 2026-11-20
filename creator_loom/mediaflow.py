"""MediaFlow's observed local HTTP contract, without private project code/config."""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__

MAX_BYTES = 32 * 1024 * 1024


class AwaitingExternal(Exception):
    def __init__(self, reason):
        self.reason = reason


def wav_info(raw):
    try:
        with wave.open(io.BytesIO(raw), "rb") as audio:
            params = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate())
            frames = audio.readframes(audio.getnframes())
            if params[0] not in {1, 2} or not audio.getnframes() or len(frames) != audio.getnframes()*params[0]*params[1]:
                raise ValueError("Invalid/truncated PCM WAV")
            return params, frames, audio.getnframes()/params[2]
    except (wave.Error, EOFError):
        raise ValueError("Expected a nonempty PCM WAV") from None


class Client:
    def __init__(self, endpoint):
        u = urlsplit(endpoint)
        if (u.scheme not in {"http", "https"} or u.hostname not in {"127.0.0.1", "localhost", "::1"}
                or u.username or u.password or u.query or u.fragment or u.path not in {"", "/"}):
            raise ValueError("MediaFlow requires a loopback root endpoint")
        self.endpoint = endpoint.rstrip("/")

    def request(self, method, path, body=None, key=None, content_type="application/json"):
        from .adapters import NoRedirect, ProviderUncertain
        headers = {"User-Agent": f"creator-loom/{__version__}"}
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = content_type
        if key:
            headers["Idempotency-Key"] = key
        req = urllib.request.Request(self.endpoint + path, data=data, headers=headers, method=method)
        try:
            # Local requests must never inherit an outbound environment proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
            with opener.open(req, timeout=20) as response:
                raw = response.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                raise ValueError("MediaFlow response exceeded size limit")
            return raw
        except (OSError, urllib.error.URLError, ProviderUncertain):
            raise ValueError("MediaFlow request failed; remote state may need reconciliation") from None

    def json(self, method, path, body=None, key=None):
        value = json.loads(self.request(method, path, body, key))
        if not isinstance(value, dict):
            raise ValueError("MediaFlow returned an invalid object")
        return value

    def upload_voice(self, path, authorized):
        if authorized is not True:
            raise ValueError("Explicit reference voice authorization is required")
        with Path(path).open("rb") as source:
            raw = source.read(10*1024*1024+1)
        if len(raw) > 10*1024*1024 or wav_info(raw)[2] > 30:
            raise ValueError("Reference voice must be PCM WAV, at most 10 MB and 30 seconds")
        boundary = "loom" + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reference.wav"\r\n'
                'Content-Type: audio/wav\r\n\r\n').encode() + raw + f"\r\n--{boundary}--\r\n".encode()
        result = json.loads(self.request("POST", "/api/assets", body, content_type=f"multipart/form-data; boundary={boundary}"))
        asset = result.get("id")
        if not isinstance(asset, str) or not re.fullmatch(r"[a-f0-9]{32}", asset):
            raise ValueError("MediaFlow did not return a voice asset ID")
        return {"asset_id": asset, "sha256": hashlib.sha256(raw).hexdigest(), "voice_authorized": True}


def split_text(text, limit):
    result = []
    text = text.strip()
    while text:
        end = min(limit, len(text))
        if len(text) > limit:
            at = max(text.rfind(mark, limit//2, limit) for mark in ["\n", "。", "！", "？", ".", "!", "?"])
            if at >= 0:
                end = at+1
            else:
                space = text.rfind(" ", limit//2, limit)
                if space >= 0:
                    end = space+1
        part, text = text[:end].strip(), text[end:].strip()
        if part:
            result.append(part)
    return result


class MediaFlow:
    def __init__(self, store):
        self.store = store

    def load(self, run_id, step_id):
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM remote_batches WHERE run_id=? AND step_id=?", (run_id, step_id)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, run_id, step_id, batch):
        with self.store.connect() as db:
            db.execute("INSERT INTO remote_batches VALUES(?,?,?) ON CONFLICT(run_id,step_id) DO UPDATE SET payload=excluded.payload",
                       (run_id, step_id, json.dumps(batch, ensure_ascii=False)))

    @staticmethod
    def matches(job, request):
        return (job.get("kind") == "tts" and job.get("source_id") == request["source_id"] and
                isinstance(job.get("params"), dict) and all(job["params"].get(k) == request[k]
                    for k in ["text", "prompt_text", "voice_authorized"]))

    def advance(self, run_id, step_id, card, text, directory):
        if not card.voice_authorized or not text.strip() or len(text) > card.max_chars:
            raise ValueError("Narration requires valid text and an authorized reference voice")
        client = Client(card.endpoint)
        pieces = split_text(text, card.segment_chars)
        requests = [{"kind": "tts", "source_id": card.voice, "text": piece,
                     "prompt_text": card.voice_prompt, "voice_authorized": True} for piece in pieces]
        fingerprint = hashlib.sha256(json.dumps([card.signature(), requests], sort_keys=True).encode()).hexdigest()
        batch = self.load(run_id, step_id)
        if batch is None:
            batch = {"fingerprint": fingerprint, "created": time.time(), "signature": card.signature(),
                     "segments": [{"request": request, "key": "loom-"+uuid.uuid4().hex,
                                   "status": "reserved", "job_id": None} for request in requests]}
            self.save(run_id, step_id, batch)
        elif batch["fingerprint"] != fingerprint:
            raise ValueError("Narration or provider settings changed; refusing to reuse remote operations")
        directory.mkdir(parents=True, exist_ok=True)
        segments_dir = directory / "segments"
        segments_dir.mkdir(exist_ok=True)
        for index, segment in enumerate(batch["segments"]):
            target = segments_dir / f"{index:04d}.wav"
            if segment["status"] == "done":
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != segment["sha256"]:
                    raise ValueError("Completed narration segment cache changed")
                segment.setdefault("bytes", target.stat().st_size)
                continue
            if segment["status"] in {"submitting", "unknown"}:
                raise AwaitingExternal("reconciliation_required")
            if segment["status"] in {"failed", "oversized"}:
                raise ValueError("MediaFlow task failed/interrupted; no new inference will be submitted")
            if segment["status"] == "reserved":
                segment["status"] = "submitting"
                self.save(run_id, step_id, batch)
                try:
                    job = client.json("POST", "/api/jobs", segment["request"], segment["key"])
                    job_id = job.get("id")
                    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id) or not self.matches(job, segment["request"]):
                        raise ValueError("Unverified submission receipt")
                    segment.update(status="waiting", job_id=job_id)
                    self.save(run_id, step_id, batch)
                except Exception:
                    segment["status"] = "unknown"
                    self.save(run_id, step_id, batch)
                    raise AwaitingExternal("reconciliation_required") from None
            try:
                job = client.json("GET", f"/api/jobs/{segment['job_id']}")
                if job.get("id") != segment["job_id"] or not self.matches(job, segment["request"]):
                    raise ValueError("Remote job identity changed")
            except Exception:
                raise AwaitingExternal("status_unavailable") from None
            if job.get("status") in {"failed", "interrupted"}:
                segment["status"] = "failed"
                self.save(run_id, step_id, batch)
                raise ValueError("MediaFlow task failed/interrupted; inspect the recorded remote ID")
            if job.get("status") != "succeeded":
                raise AwaitingExternal("remote_pending")
            if "speech.wav" not in (job.get("result") or {}).get("files", []):
                raise AwaitingExternal("artifact_unavailable")
            try:
                raw = client.request("GET", f"/api/jobs/{segment['job_id']}/files/speech.wav")
                wav_info(raw)
            except Exception:
                raise AwaitingExternal("download_unavailable") from None
            if len(raw) + sum(s.get("bytes", 0) for s in batch["segments"] if s["status"] == "done") > MAX_BYTES:
                segment["status"] = "oversized"
                self.save(run_id, step_id, batch)
                raise ValueError("Narration byte limit reached; no later segments will be submitted")
            temp = target.with_suffix(".part")
            temp.write_bytes(raw)
            temp.replace(target)
            segment.update(status="done", sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            self.save(run_id, step_id, batch)
        output = directory / "narration.wav"
        params, frames, cues, position = None, [], [], 0.0
        for index, segment in enumerate(batch["segments"]):
            info, data, duration = wav_info((segments_dir / f"{index:04d}.wav").read_bytes())
            if params is not None and info != params:
                raise ValueError("Narration segments have incompatible PCM formats")
            params = info
            frames.append(data)
            if sum(map(len, frames)) > MAX_BYTES:
                raise ValueError("Combined narration exceeds 32 MB")
            cues.append({"start": position, "end": position+duration, "text": segment["request"]["text"], "job_id": segment["job_id"]})
            position += duration
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(params[0])
            audio.setsampwidth(params[1])
            audio.setframerate(params[2])
            audio.writeframes(b"".join(frames))
        (directory / "timings.json").write_text(json.dumps({"alignment": "segment durations; not word alignment", "segments": cues}, ensure_ascii=False))
        (directory / "mediaflow.json").write_text(json.dumps({"fingerprint": fingerprint,
            "job_ids": [s["job_id"] for s in batch["segments"]]}, indent=2))
        return output

    def reconcile(self, run_id, step_id, segment_index, job_id, card):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid MediaFlow job ID")
        batch = self.load(run_id, step_id)
        if not batch or type(segment_index) is not int or not 0 <= segment_index < len(batch["segments"]):
            raise ValueError("Unknown narration segment")
        segment = batch["segments"][segment_index]
        if segment["status"] not in {"submitting", "unknown"} or batch["signature"] != card.signature():
            raise ValueError("Only an unconfirmed submission can be reconciled")
        job = Client(card.endpoint).json("GET", "/api/jobs/" + job_id)
        if job.get("id") != job_id or not self.matches(job, segment["request"]):
            raise ValueError("Remote task does not match the frozen narration request")
        if any(s.get("job_id") == job_id for i, s in enumerate(batch["segments"]) if i != segment_index):
            raise ValueError("Remote job is already bound to another segment")
        segment.update(status="waiting", job_id=job_id)
        self.save(run_id, step_id, batch)
        return {"segment": segment_index, "job_id": job_id, "status": "bound", "submitted": False}
