"""Versioned, shot-reviewed local editing of already approved creative artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path

from .domain import bounded, identifier
from .engine import Engine, digest
from .locking import run_lock
from . import timeline_media as media


class Timeline:
    def __init__(self, store):
        self.store = store
        self.engine = Engine(store, [])

    def lock(self, name):
        identifier(name)
        return run_lock(self.store, hashlib.sha256(("timeline:"+name).encode()).hexdigest())

    def reference(self, ref, kind):
        if not isinstance(ref, dict) or not {"run", "step", "file"} <= set(ref) or set(ref)-{"run", "step", "file", "sha256"}:
            raise ValueError("Source needs run, step, file and optional sha256")
        identifier(ref["run"]); identifier(ref["step"])
        run = self.store.run(ref["run"])
        if run["status"] != "approved":
            raise ValueError("Timeline sources must be approved creative artifacts")
        self.engine.verify_artifacts(run)
        step = next((s for s in run["steps"] if s["id"] == ref["step"]), None)
        if not step:
            raise ValueError("Unknown source step")
        result = next((r for r in [step["result"], *step["result"]["supplements"]] if r["file"] == ref["file"]), None)
        if not result or (ref.get("sha256") is not None and ref["sha256"] != result["sha256"]):
            raise ValueError("Source is not a matching reviewed artifact")
        path = self.engine.artifact(run["id"], result)
        allowed = {"visual": {".png", ".ppm", ".mp4"}, "audio": {".wav"}}
        if path.suffix not in allowed[kind] or path.stat().st_size > media.MAX_BYTES:
            raise ValueError("Unsupported source type or source larger than 128 MB")
        info = media.probe(path)
        stream_kind = "audio" if kind == "audio" else "video"
        if not any(s["codec_type"] == stream_kind for s in info["streams"]):
            raise ValueError("Source lacks the required media stream")
        return {"run": run["id"], "step": step["id"], "file": result["file"], "sha256": result["sha256"]}, path, info

    def normalize(self, spec):
        required = {"title", "shots"}
        optional = {"width", "height", "fps", "narration", "music", "captions", "duration"}
        if not isinstance(spec, dict) or not required <= set(spec) or set(spec)-required-optional:
            raise ValueError("Timeline needs title, shots and supported canvas/audio/caption fields")
        if not isinstance(spec["title"], str) or not 1 <= len(spec["title"].strip()) <= 200:
            raise ValueError("Timeline title must contain 1–200 characters")
        width, height, fps = spec.get("width", 1280), spec.get("height", 720), spec.get("fps", 24)
        if type(width) is not int or type(height) is not int or (width, height) not in {(1280, 720), (720, 1280), (640, 360), (360, 640)}:
            raise ValueError("Choose a supported landscape or portrait canvas")
        if type(fps) is not int or fps not in {24, 25, 30}:
            raise ValueError("Timeline fps must be 24, 25 or 30")
        if not isinstance(spec["shots"], list) or not 1 <= len(spec["shots"]) <= 120:
            raise ValueError("Timeline needs 1–120 shots")
        shots, seen, total = [], set(), 0
        for shot in spec["shots"]:
            if not isinstance(shot, dict) or not {"id", "source", "duration"} <= set(shot) or set(shot)-{"id", "source", "duration", "in", "motion"}:
                raise ValueError("Shot needs id, source, duration and optional in/motion")
            identifier(shot["id"])
            if shot["id"] in seen:
                raise ValueError("Shot IDs must be distinct")
            seen.add(shot["id"])
            seconds = bounded(shot["duration"], 0.25, 120, "shot duration")
            frames = round(seconds*fps)
            if abs(frames/fps-seconds) > 0.000001:
                raise ValueError("Shot durations must use exact frame boundaries")
            start = bounded(shot.get("in", 0), 0, 3600, "shot in point")
            motion = shot.get("motion", "still")
            if motion not in {"still", "zoom-in"}:
                raise ValueError("Shot motion must be still or zoom-in")
            ref, path, info = self.reference(shot["source"], "visual")
            if path.suffix == ".mp4":
                if start+seconds > media.duration(info, "video")+0.000001:
                    raise ValueError("Shot exceeds its source video duration")
                if motion != "still":
                    raise ValueError("Zoom motion currently requires a still image")
            elif start != 0:
                raise ValueError("Still images have no in point")
            shots.append({"id": shot["id"], "source": ref, "duration": frames/fps, "in": start, "motion": motion})
            total += frames
        seconds = total/fps
        if seconds > 600:
            raise ValueError("Timeline exceeds ten minutes")
        if "duration" in spec and abs(bounded(spec["duration"], 0.25, 600, "timeline duration")-seconds) > 0.000001:
            raise ValueError("Derived duration must match the sum of shot durations")
        tracks = {}
        for role in ["narration", "music"]:
            track = spec.get(role)
            if track is None:
                tracks[role] = None
                continue
            if not isinstance(track, dict) or "source" not in track or set(track)-{"source", "in", "gain", "loop"}:
                raise ValueError("Audio track needs source and optional in/gain/loop")
            start = bounded(track.get("in", 0), 0, 3600, "audio in point")
            gain = bounded(track.get("gain", 1 if role == "narration" else 0.15), 0, 2, "audio gain")
            loop = track.get("loop", False)
            if type(loop) is not bool or (loop and (role != "music" or start != 0)):
                raise ValueError("Only music from in=0 can loop")
            ref, _, info = self.reference(track["source"], "audio")
            if start >= media.duration(info, "audio"):
                raise ValueError("Audio in point is outside its source")
            tracks[role] = {"source": ref, "in": start, "gain": gain, "loop": loop}
        captions, end = [], 0.0
        if not isinstance(spec.get("captions", []), list) or len(spec.get("captions", [])) > 1000:
            raise ValueError("Provide at most 1000 caption cues")
        for caption in spec.get("captions", []):
            if not isinstance(caption, dict) or set(caption) != {"start", "end", "text"}:
                raise ValueError("Caption needs start, end and plain text")
            start = bounded(caption["start"], 0, seconds, "caption start")
            stop = bounded(caption["end"], 0, seconds, "caption end")
            text = caption["text"]
            if start < end or stop-start < 0.001:
                raise ValueError("Caption cues must be ordered, non-overlapping and at least one millisecond")
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500 or any(ord(c) < 32 for c in text) or any(c in text for c in "<>"):
                raise ValueError("Caption text must be 1–500 plain characters without markup or control characters")
            captions.append({"start": start, "end": stop, "text": text})
            end = stop
        return {"title": spec["title"].strip(), "width": width, "height": height, "fps": fps,
                "duration": seconds, "shots": shots, **tracks, "captions": captions}

    def create(self, name, spec):
        identifier(name)
        normalized = self.normalize(spec)
        with self.lock(name), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO timelines(id,current_version) VALUES(?,1)", (name,))
            db.execute("INSERT INTO timeline_versions(timeline_id,version,spec,state) VALUES(?,1,?,'draft')", (name, json.dumps(normalized)))
            self.store.event(db, "timeline_created", name, {"version": 1})
        return self.inspect(name)

    def inspect(self, name, version=None):
        identifier(name)
        if version is not None and (type(version) is not int or version < 1):
            raise ValueError("Timeline version must be a positive integer")
        with self.store.connect() as db:
            timeline = db.execute("SELECT * FROM timelines WHERE id=?", (name,)).fetchone()
            if not timeline:
                raise ValueError("Unknown timeline")
            version = timeline["current_version"] if version is None else version
            row = db.execute("SELECT * FROM timeline_versions WHERE timeline_id=? AND version=?", (name, version)).fetchone()
            if not row:
                raise ValueError("Unknown timeline version")
            reviews = [dict(r) for r in db.execute("SELECT shot_id,decision,note FROM shot_reviews WHERE timeline_id=? AND version=?", (name, version))]
        return {"id": name, "version": version, "current_version": timeline["current_version"], "state": row["state"],
                "spec": json.loads(row["spec"]), "reviews": reviews, "outputs": json.loads(row["outputs"]) if row["outputs"] else None}

    def require_current(self, timeline, version):
        if type(version) is not int or version != timeline["current_version"]:
            raise ValueError("Timeline changed; inspect the current version before editing or reviewing")

    def revise(self, name, spec, version):
        normalized = self.normalize(spec)
        with self.lock(name), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self.inspect(name)
            self.require_current(current, version)
            # Holding the OS lock proves an old rendering worker is no longer live.
            db.execute("UPDATE timeline_versions SET state='interrupted' WHERE timeline_id=? AND state='rendering'", (name,))
            db.execute("UPDATE timelines SET current_version=? WHERE id=?", (version+1, name))
            db.execute("INSERT INTO timeline_versions(timeline_id,version,spec,state) VALUES(?,?,?,'draft')", (name, version+1, json.dumps(normalized)))
            self.store.event(db, "timeline_revised", name, {"version": version+1})
        return self.inspect(name)

    def review_shot(self, name, shot, version, decision, note):
        if decision not in {"approve", "reject"} or not isinstance(note, str) or not 5 <= len(note.strip()) <= 2000:
            raise ValueError("Provide approve/reject and a 5–2000 character review note")
        with self.lock(name), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            timeline = self.inspect(name)
            self.require_current(timeline, version)
            if timeline["state"] != "draft" or shot not in {s["id"] for s in timeline["spec"]["shots"]}:
                raise ValueError("Only draft shots can be reviewed")
            self.verify_sources(timeline)
            db.execute("INSERT INTO shot_reviews VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)", (name, version, shot, decision, note))
            self.store.event(db, "shot_reviewed", name, {"version": version, "shot": shot, "decision": decision})
        return self.inspect(name)

    def verify_sources(self, timeline):
        refs = [(s["source"], "visual") for s in timeline["spec"]["shots"]]
        refs += [(timeline["spec"][k]["source"], "audio") for k in ["narration", "music"] if timeline["spec"][k]]
        result = {}
        for ref, kind in refs:
            _, path, _ = self.reference(ref, kind)
            result[ref["sha256"]] = path
        return result

    def seal(self, name, version):
        with self.lock(name), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            timeline = self.inspect(name)
            self.require_current(timeline, version)
            if timeline["state"] != "draft" or {r["shot_id"] for r in timeline["reviews"] if r["decision"] == "approve"} != {s["id"] for s in timeline["spec"]["shots"]}:
                raise ValueError("Approve every shot before sealing the edit")
            self.verify_sources(timeline)
            db.execute("UPDATE timeline_versions SET state='sealed' WHERE timeline_id=? AND version=?", (name, version))
            self.store.event(db, "timeline_sealed", name, {"version": version})
        return self.inspect(name)

    def directory(self, name, version):
        return self.store.root/"timelines"/name/str(version)

    @staticmethod
    def public_edit(spec):
        result = {k: spec[k] for k in ["title", "width", "height", "fps", "duration", "captions"]}
        result["shots"] = [{k: shot[k] for k in ["id", "duration", "in", "motion"]} |
                           {"source_sha256": shot["source"]["sha256"]} for shot in spec["shots"]]
        for role in ["narration", "music"]:
            track = spec[role]
            result[role] = {k: track[k] for k in ["in", "gain", "loop"]} | {"source_sha256": track["source"]["sha256"]} if track else None
        result["caption_alignment"] = "Explicit editor timings; not automatic speech or word alignment"
        return result

    def render(self, name, version):
        with self.lock(name):
            timeline = self.inspect(name)
            self.require_current(timeline, version)
            if timeline["state"] in {"needs_review", "approved"}:
                self.verify_outputs(timeline)
                return timeline
            if timeline["state"] == "rendering":
                with self.store.connect() as db:
                    db.execute("UPDATE timeline_versions SET state='interrupted' WHERE timeline_id=? AND version=?", (name, version))
                raise ValueError("Previous local render was interrupted; create a new revision to render again")
            if timeline["state"] != "sealed":
                raise ValueError("Seal the reviewed timeline before rendering")
            sources = self.verify_sources(timeline)
            with self.store.connect() as db:
                db.execute("UPDATE timeline_versions SET state='rendering' WHERE timeline_id=? AND version=?", (name, version))
            directory = self.directory(name, version)
            directory.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(prefix="work-", dir=directory) as temporary:
                    work = Path(temporary)
                    names = media.render(timeline["spec"], sources, work)
                    # Detect source changes during rendering before offering a result.
                    self.verify_sources(timeline)
                    (work/"timeline.json").write_text(json.dumps(self.public_edit(timeline["spec"]), ensure_ascii=False, indent=2))
                    outputs = []
                    for filename in [*names, "timeline.json"]:
                        path = work/filename
                        outputs.append({"file": filename, "sha256": digest(path), "bytes": path.stat().st_size})
                    if sum(o["bytes"] for o in outputs) > media.MAX_BYTES:
                        raise ValueError("Timeline delivery exceeds 128 MB")
                    for filename in [*names, "timeline.json"]:
                        (work/filename).replace(directory/filename)
                with self.store.connect() as db:
                    db.execute("UPDATE timeline_versions SET state='needs_review',outputs=? WHERE timeline_id=? AND version=?", (json.dumps(outputs), name, version))
                    self.store.event(db, "timeline_rendered", name, {"version": version, "outputs": outputs})
            except Exception:
                with self.store.connect() as db:
                    db.execute("UPDATE timeline_versions SET state='failed' WHERE timeline_id=? AND version=?", (name, version))
                    self.store.event(db, "timeline_render_failed", name, {"version": version})
                raise ValueError("Local timeline render failed; sources were preserved. Revise the edit before another attempt") from None
        return self.inspect(name)

    def verify_outputs(self, timeline):
        self.verify_sources(timeline)
        if not timeline["outputs"]:
            raise ValueError("Timeline has no completed render")
        directory = self.directory(timeline["id"], timeline["version"]).resolve()
        for output in timeline["outputs"]:
            path = (directory/output["file"]).resolve()
            if not path.is_relative_to(directory) or not path.is_file() or digest(path) != output["sha256"]:
                raise ValueError("Rendered artifact is missing or changed")

    def approve(self, name, version):
        with self.lock(name), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            timeline = self.inspect(name)
            self.require_current(timeline, version)
            if timeline["state"] != "needs_review":
                raise ValueError("Only a finished timeline can be approved")
            self.verify_outputs(timeline)
            db.execute("UPDATE timeline_versions SET state='approved' WHERE timeline_id=? AND version=?", (name, version))
            self.store.event(db, "timeline_approved", name, {"version": version, "outputs": timeline["outputs"]})
        return self.inspect(name)

    def export(self, name, version=None):
        timeline = self.inspect(name, version)
        if timeline["state"] != "approved":
            raise ValueError("Approve the rendered timeline before exporting")
        self.verify_outputs(timeline)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for output in timeline["outputs"]:
                info = zipfile.ZipInfo(output["file"], (1980, 1, 1, 0, 0, 0))
                info.create_system = 0
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (self.directory(name, timeline["version"])/output["file"]).read_bytes())
        directory = self.store.root/"timeline_exports"
        directory.mkdir(exist_ok=True)
        path = directory/(name+"-"+str(timeline["version"])+".zip")
        path.write_bytes(stream.getvalue())
        return {"file": str(path), "version": timeline["version"], "uploaded": False}
