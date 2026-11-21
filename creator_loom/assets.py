"""Explicitly licensed local media imports with normalized, reviewed artifacts."""

from __future__ import annotations

import hashlib
import io
import zipfile
import json
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .domain import bounded, identifier
from .locking import run_lock
from . import timeline_media as media

MAX_SOURCE = 64 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def public_url(value, suno=False):
    if value == "":
        return value
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError("Source link must be a short public HTTPS URL")
    if any(ord(c) < 32 for c in value):
        raise ValueError("Source links must not contain control characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("Source link must be a valid HTTPS URL") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or port not in {None, 443}:
        raise ValueError("Source link must be HTTPS without credentials, query or fragment")
    if suno and (parsed.hostname.lower() not in {"suno.com", "www.suno.com"} or not re.fullmatch(r"/(?:song|s)/[A-Za-z0-9_-]{6,100}/?", parsed.path)):
        raise ValueError("Provide a public Suno song/share URL; it is an operator-reported reference, not a verified receipt")
    return value


class Assets:
    def __init__(self, store):
        self.store = store

    def inspect(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM media_assets WHERE id=?", (name,)).fetchone()
        if not row:
            raise ValueError("Unknown media asset")
        return {"id": name, "state": row["state"], "profile": row["profile"], "payload": json.loads(row["payload"]), "review": json.loads(row["review"]) if row["review"] else None}

    def directory(self, name):
        identifier(name)
        return self.store.root/"assets"/name

    def verify(self, name, approved=False, _depth=0):
        if _depth > 16:
            raise ValueError("Media derivation chain exceeds 16 references")
        asset = self.inspect(name)
        if approved and asset["state"] != "approved":
            raise ValueError("Media asset must be approved before reuse")
        root = self.directory(name).resolve()
        payload = asset["payload"]
        path = (root/payload["file"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != payload["sha256"]:
            raise ValueError("Imported media is missing or changed")
        source = root/"source.bin"
        if not source.is_file() or sha(source.read_bytes()) != payload["source_sha256"]:
            raise ValueError("Imported source provenance is missing or changed")
        if payload.get("parent"):
            parent, _ = self.verify(payload["parent"]["asset"], approved=True, _depth=_depth+1)
            if parent["payload"]["sha256"] != payload["parent"]["sha256"] or parent["payload"]["kind"] != "audio":
                raise ValueError("Derived media parent changed")
        return asset, path

    def reference(self, ref, kind=None):
        if not isinstance(ref, dict) or "asset" not in ref or set(ref)-{"asset", "sha256", "kind"}:
            raise ValueError("Asset reference needs asset and optional sha256/kind")
        asset, path = self.verify(ref["asset"], approved=True)
        payload = asset["payload"]
        if ref.get("sha256", payload["sha256"]) != payload["sha256"] or ref.get("kind", payload["kind"]) != payload["kind"]:
            raise ValueError("Media reference no longer matches the approved asset")
        if kind == "audio" and payload["kind"] != "audio" or kind == "visual" and payload["kind"] not in {"image", "video"}:
            raise ValueError("Selected asset has the wrong media type")
        return {"asset": asset["id"], "sha256": payload["sha256"], "kind": payload["kind"]}, path, payload

    def list(self, profile, state=None):
        identifier(profile)
        if state not in {None, "needs_review", "approved", "rejected"}:
            raise ValueError("Unknown asset review state")
        with self.store.connect() as db:
            rows = db.execute("SELECT id FROM media_assets WHERE profile=? AND (? IS NULL OR state=?) ORDER BY rowid DESC LIMIT 300", (profile, state, state)).fetchall()
        return [self.inspect(row["id"]) for row in rows]

    @staticmethod
    def metadata(meta):
        if not isinstance(meta, dict) or not {"title", "kind", "rights", "rights_note", "authorized"} <= set(meta) or set(meta)-{"title", "kind", "rights", "rights_note", "authorized", "attribution", "license_url", "origin", "profile"}:
            raise ValueError("Media import needs title, kind, rights, rights_note and explicit authorization")
        if meta["authorized"] is not True:
            raise ValueError("Explicit authorization for the imported media is required")
        if meta["kind"] not in {"image", "audio", "video"} or meta["rights"] not in {"owned", "licensed", "public-domain"}:
            raise ValueError("Choose a supported media kind and source rights")
        for key, low, high in [("title", 1, 200), ("rights_note", 10, 2000)]:
            if not isinstance(meta[key], str) or not low <= len(meta[key].strip()) <= high:
                raise ValueError("Provide a title and a meaningful private rights note")
        attribution = meta.get("attribution", "")
        if not isinstance(attribution, str) or len(attribution) > 2000 or (meta["rights"] != "owned" and not attribution.strip()):
            raise ValueError("Licensed/public-domain media needs public attribution; owned media may include credits too")
        origin = meta.get("origin", {"service": "external", "reference": ""})
        if not isinstance(origin, dict) or set(origin)-{"service", "reference"} or origin.get("service") not in {"external", "suno"}:
            raise ValueError("Origin service must be external or suno")
        reference = public_url(origin.get("reference", ""), suno=origin["service"] == "suno")
        profile = identifier(meta.get("profile", "default"))
        return {"title": meta["title"].strip(), "kind": meta["kind"], "rights": meta["rights"], "rights_note": meta["rights_note"].strip(),
                "attribution": attribution, "license_url": public_url(meta.get("license_url", "")), "origin": {"service": origin["service"], "reference": reference}, "profile": profile}

    def import_file(self, path, meta, request_key=None):
        with Path(path).open("rb") as source:
            raw = source.read(MAX_SOURCE+1)
        return self.import_bytes(raw, meta, request_key)

    def import_bytes(self, raw, meta, request_key=None, parent=None, transform=None):
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_SOURCE:
            raise ValueError("Source media must contain 1 byte–64 MB")
        metadata = self.metadata(meta)
        if request_key is not None:
            identifier(request_key)
        fingerprint = sha(json.dumps([sha(raw), metadata, parent, transform], sort_keys=True).encode())
        lock = "asset-"+(sha(request_key.encode()) if request_key else fingerprint)[:56]
        with run_lock(self.store, lock):
            if request_key:
                with self.store.connect() as db:
                    prior = db.execute("SELECT * FROM asset_imports WHERE id=?", (request_key,)).fetchone()
                if prior:
                    if prior["fingerprint"] != fingerprint:
                        raise ValueError("Import key was used for different media or rights")
                    self.verify(prior["asset_id"])
                    return self.inspect(prior["asset_id"])
            kind = metadata["kind"]
            if kind == "image":
                demux = "png_pipe" if raw.startswith(b"\x89PNG\r\n\x1a\n") else "jpeg_pipe" if raw.startswith(b"\xff\xd8\xff") else None
            elif kind == "audio":
                demux = "wav" if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE" else "mp3"
            else:
                demux = "mov" if b"ftyp" in raw[:64] else None
            if demux is None:
                raise ValueError("Expected PNG/JPEG image, WAV/MP3 audio or MP4 video")
            name = uuid.uuid4().hex
            root = self.directory(name)
            root.mkdir(parents=True)
            try:
                source = root/"source.bin"
                source.write_bytes(raw)
                probe = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-f", demux]
                if demux == "mov":
                    probe += ["-enable_drefs", "0", "-use_absolute_path", "0"]
                info = json.loads(media.command(probe+["-show_entries", "stream=codec_type,width,height,duration:format=duration", "-of", "json", str(source)], timeout=20))
                streams = info.get("streams", [])
                target = next((s for s in streams if s["codec_type"] == ("audio" if kind == "audio" else "video")), None)
                if not target:
                    raise ValueError("Source does not match the declared media kind")
                if kind != "audio" and not all(type(target.get(k)) is int and 16 <= target[k] <= 4096 for k in ["width", "height"]):
                    raise ValueError("Imported visual dimensions must be 16–4096 pixels")
                if kind != "image" and media.duration(info, "audio" if kind == "audio" else "video") > 600:
                    raise ValueError("Imported audio/video must not exceed ten minutes")
                args = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-filter_threads", "1", "-protocol_whitelist", "file,pipe", "-f", demux]
                if demux == "mov":
                    args += ["-enable_drefs", "0", "-use_absolute_path", "0"]
                args += ["-i", str(source), "-map_metadata", "-1", "-map_chapters", "-1"]
                filename = {"image": "image.png", "audio": "audio.wav", "video": "video.mp4"}[kind]
                if kind == "image":
                    args += ["-map", "0:v:0", "-frames:v", "1", "-c:v", "png", "-threads", "1"]
                elif kind == "audio":
                    args += ["-map", "0:a:0", "-vn", "-sn", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
                else:
                    # Source clip audio is not part of timeline mixing; retain a silent visual here.
                    args += ["-map", "0:v:0", "-an", "-sn", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart"]
                output = root/filename
                args += ["-fs", str(media.MAX_BYTES), str(output)]
                media.command(args, timeout=240)
                normalized = media.probe(output)
                seconds = None if kind == "image" else media.duration(normalized, "audio" if kind == "audio" else "video")
                if seconds and abs(seconds-media.duration(info, "audio" if kind == "audio" else "video")) > 0.1:
                    raise ValueError("Media normalization changed duration unexpectedly")
                if output.stat().st_size > media.MAX_BYTES:
                    raise ValueError("Normalized media exceeds 128 MB")
                payload = {**metadata, "file": filename, "sha256": sha(output.read_bytes()), "source_sha256": sha(raw), "bytes": output.stat().st_size,
                           "duration": seconds, "parent": parent, "transform": transform,
                           "normalization": "Metadata removed; audio converted to stereo PCM; video normalized without source audio"}
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("INSERT INTO media_assets(id,profile,state,payload) VALUES(?,?,'needs_review',?)", (name, metadata["profile"], json.dumps(payload)))
                    if request_key:
                        db.execute("INSERT INTO asset_imports VALUES(?,?,?)", (request_key, fingerprint, name))
                    self.store.event(db, "media_imported", name, {"kind": kind, "source_sha256": payload["source_sha256"]})
            except Exception:
                import shutil
                shutil.rmtree(root, ignore_errors=True)
                raise ValueError("Media import failed; check its format, bounds and rights privately. No remote request was sent") from None
        return self.inspect(name)

    def review(self, name, decision, note):
        if decision not in {"approve", "reject"} or not isinstance(note, str) or not 5 <= len(note.strip()) <= 2000:
            raise ValueError("Review needs approve/reject and a 5–2000 character note")
        with run_lock(self.store, "review-"+identifier(name)), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            asset, _ = self.verify(name)
            review = {"decision": decision, "note": note}
            if asset["review"]:
                if asset["review"] == review:
                    return asset
                raise ValueError("Asset review is immutable; import a new revision")
            db.execute("UPDATE media_assets SET state=?,review=? WHERE id=?", ("approved" if decision == "approve" else "rejected", json.dumps(review), name))
            self.store.event(db, "media_reviewed", name, {"decision": decision})
        return self.inspect(name)

    def credits(self, name):
        asset, _ = self.verify(name, approved=True)
        p = asset["payload"]
        return {k: p[k] for k in ["title", "kind", "rights", "attribution", "license_url", "source_sha256", "sha256"]} | {
            "transform": p.get("transform"), "parent_sha256": p["parent"]["sha256"] if p.get("parent") else None}

    def bundle(self, name):
        asset, path = self.verify(name, approved=True)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, raw in [(asset["payload"]["file"], path.read_bytes()), ("credits.json", json.dumps(self.credits(name), ensure_ascii=False, indent=2).encode())]:
                info = zipfile.ZipInfo(filename, (1980, 1, 1, 0, 0, 0))
                info.create_system = 0; info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, raw)
        return stream.getvalue()

    def derive_audio(self, name, settings, request_key=None):
        ref, path, payload = self.reference({"asset": name}, "audio")
        self.verify(name, approved=True, _depth=1)
        if not isinstance(settings, dict) or set(settings)-{"start", "duration", "tempo", "semitones", "mode"}:
            raise ValueError("Audio edit accepts start, duration, tempo, semitones and mode")
        start = bounded(settings.get("start", 0), 0, payload["duration"], "audio trim start")
        seconds = bounded(settings.get("duration", payload["duration"]-start), 0.1, 600, "audio trim duration")
        tempo = bounded(settings.get("tempo", 1), 0.5, 2, "tempo")
        pitch = bounded(settings.get("semitones", 0), -12, 12, "semitones")
        mode = settings.get("mode", "independent")
        if start+seconds > payload["duration"]+1e-6 or seconds/tempo > 600 or mode not in {"independent", "tape"} or mode == "tape" and pitch != 0:
            raise ValueError("Audio edit exceeds its source/output duration or uses an incompatible tape/pitch combination")
        transform = {"start": start, "duration": seconds, "tempo": tempo, "semitones": pitch, "mode": mode}
        ratio = tempo if mode == "tape" else 2**(pitch/12)
        filters = [f"atrim=start={start}:duration={seconds}", "asetpts=PTS-STARTPTS", f"asetrate=48000*{ratio}", "aresample=48000"]
        if mode == "independent":
            # Decompose atempo to its widely supported 0.5–2 range.
            change = tempo/ratio
            while change < 0.5:
                filters.append("atempo=0.5"); change /= 0.5
            while change > 2:
                filters.append("atempo=2"); change /= 2
            filters.append(f"atempo={change}")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/"audio.wav"
            media.command(["ffmpeg", "-nostdin", "-y", "-v", "error", "-protocol_whitelist", "file,pipe", "-f", "wav", "-i", str(path),
                           "-af", ",".join(filters), "-map_metadata", "-1", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(output)], timeout=120)
            self.reference(ref, "audio")
            meta = {k: payload[k] for k in ["title", "kind", "rights", "rights_note", "attribution", "license_url", "origin", "profile"]}
            meta["title"] = meta["title"][:175] + " · reference edit"
            meta["authorized"] = True
            return self.import_bytes(output.read_bytes(), meta, request_key, parent=ref, transform=transform)
