"""Reviewed music briefs and explicit, operator-mediated Suno handoff boundaries."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile

from .assets import Assets, public_url
from .domain import Brief, identifier
from .engine import Engine
from .locking import run_lock


class Music:
    def __init__(self, store, cards):
        self.store, self.engine, self.assets = store, Engine(store, cards), Assets(store)

    def lock(self, name):
        identifier(name)
        return run_lock(self.store, hashlib.sha256(("music:"+name).encode()).hexdigest())

    def inspect(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM music_projects WHERE id=?", (name,)).fetchone()
        if not row:
            raise ValueError("Unknown music project")
        value = dict(row)
        for key in ["definition", "handoff", "external", "result"]:
            value[key] = json.loads(value[key]) if value[key] else None
        attributions = [value["definition"].get("lyrics_attribution", ""), value["definition"].get("lyrics_license_url", "")]
        if value["definition"].get("source"):
            declared = self.assets.inspect(value["definition"]["source"]["asset"])["payload"]
            attributions.extend([declared["attribution"], declared["license_url"]])
        value["required_attributions"] = list(dict.fromkeys(a for a in attributions if a.strip()))
        value["run_status"] = self.store.run(value["run_id"])["status"]
        return value

    def list(self, profile):
        identifier(profile)
        with self.store.connect() as db:
            rows = db.execute("SELECT id,definition FROM music_projects ORDER BY rowid DESC").fetchall()
        return [self.inspect(r["id"]) for r in rows if json.loads(r["definition"])["profile"] == profile][:300]

    def create(self, name, spec, request_key=None):
        identifier(name)
        if not isinstance(spec, dict) or not {"title", "intent", "lyrics", "lyrics_rights", "rights_note", "adaptation_authorized"} <= set(spec) or set(spec)-{"title", "intent", "lyrics", "rights_note", "adaptation_authorized", "source", "profile", "language", "budget", "local_only", "max_latency", "lyrics_rights", "lyrics_attribution", "lyrics_license_url"}:
            raise ValueError("Music brief needs title, intent, authorized lyrics and a private rights note")
        if spec["adaptation_authorized"] is not True:
            raise ValueError("Explicit authorization for lyric adaptation and reference use is required")
        for key, low, high in [("title", 1, 200), ("intent", 10, 2000), ("lyrics", 0, 5000), ("rights_note", 10, 2000)]:
            if not isinstance(spec[key], str) or not low <= len(spec[key].strip()) <= high:
                raise ValueError("Provide a bounded music title, intent, lyrics and rights note")
        lyrics_rights = spec.get("lyrics_rights", "owned")
        lyrics_credit = spec.get("lyrics_attribution", "")
        if lyrics_rights not in {"owned", "licensed", "public-domain"} or not isinstance(lyrics_credit, str) or len(lyrics_credit) > 2000 or (lyrics_rights != "owned" and not lyrics_credit.strip()):
            raise ValueError("Licensed/public-domain lyrics need public attribution")
        lyric_license = public_url(spec.get("lyrics_license_url", ""))
        source = self.assets.reference(spec["source"], "audio")[0] if spec.get("source") else None
        topic = json.dumps({"title": spec["title"], "creative_intent": spec["intent"], "authorized_lyrics": spec["lyrics"],
                            "reference": "Reference audio is for the operator only; these text models have not heard it."}, ensure_ascii=False)
        brief = Brief(topic, "song", spec.get("language", "zh"), spec.get("profile", "default"), spec.get("budget", 1), spec.get("local_only", True), spec.get("max_latency", 300))
        definition = {**spec, "lyrics_rights": lyrics_rights, "lyrics_attribution": lyrics_credit, "lyrics_license_url": lyric_license, "source": source, "profile": brief.profile, "language": brief.language}
        fingerprint = hashlib.sha256(json.dumps([name, definition, brief.__dict__], sort_keys=True).encode()).hexdigest()
        with self.lock(name):
            if request_key:
                identifier(request_key)
                with self.store.connect() as db:
                    prior = db.execute("SELECT * FROM music_requests WHERE id=?", (request_key,)).fetchone()
                if prior:
                    if prior["fingerprint"] != fingerprint:
                        raise ValueError("Music request key was used for a different brief")
                    return self.inspect(prior["project_id"])
            plan = self.engine.plan(brief, input_assets=[source] if source else [])
            plan["public_credits"] = [{"title": spec["title"]+" · lyric source", "rights": lyrics_rights, "attribution": lyrics_credit, "license_url": lyric_license}]
            run_id = uuid.uuid4().hex
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.engine.persist(db, run_id, plan)
                db.execute("INSERT INTO music_projects(id,definition,run_id,state) VALUES(?,?,?,'planned')", (name, json.dumps(definition), run_id))
                if request_key:
                    db.execute("INSERT INTO music_requests VALUES(?,?,?)", (request_key, fingerprint, name))
                self.store.event(db, "music_planned", name, {"run": run_id, "audio_sent_to_model": False})
        return self.inspect(name)

    def approved_plan(self, project):
        run = self.store.run(project["run_id"])
        if run["status"] != "approved":
            raise ValueError("Inspect, execute and approve the lyric/direction run before handoff")
        self.engine.verify_artifacts(run)
        return run

    def handoff(self, name, transfer_authorized, note, include_audio=False):
        if transfer_authorized is not True or type(include_audio) is not bool or not isinstance(note, str) or not 10 <= len(note.strip()) <= 2000:
            raise ValueError("Handoff needs explicit transfer authorization and a 10–2000 character note")
        with self.lock(name):
            project = self.inspect(name)
            run = self.approved_plan(project)
            decision = {"include_audio": include_audio, "note": note}
            if project["handoff"]:
                if project["handoff"]["authorization"] != decision:
                    raise ValueError("Handoff authorization is frozen; create a new music project for a different transfer")
                self.handoff_bytes(name)
                return project
            stream = io.BytesIO()
            manifest = {"title": project["definition"]["title"], "intent": project["definition"]["intent"], "language": project["definition"]["language"],
                        "mode": "Manual Suno handoff. This package does not submit, generate or confirm any remote job.", "files": [], "credits": list(run["plan"].get("public_credits", []))}
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                def write(filename, raw):
                    info = zipfile.ZipInfo(filename, (1980, 1, 1, 0, 0, 0)); info.create_system = 0; info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, raw)
                    manifest["files"].append({"file": filename, "sha256": hashlib.sha256(raw).hexdigest()})
                for step in run["steps"]:
                    write(step["id"]+".md", self.engine.artifact(run["id"], step["result"]).read_bytes())
                source = project["definition"]["source"]
                if source:
                    ref, path, _ = self.assets.reference(source, "audio")
                    manifest["credits"].append(self.assets.credits(ref["asset"]))
                    if include_audio:
                        write("reference.wav", path.read_bytes())
                elif include_audio:
                    raise ValueError("This project has no approved reference audio")
                write("brief.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
            raw = stream.getvalue()
            if len(raw) > 128*1024*1024:
                raise ValueError("Handoff exceeds 128 MB")
            directory = self.store.root/"music"/name
            directory.mkdir(parents=True, exist_ok=True)
            (directory/"handoff.zip").write_bytes(raw)
            handoff = {"sha256": hashlib.sha256(raw).hexdigest(), "authorization": decision, "remote_submitted": False}
            with self.store.connect() as db:
                db.execute("UPDATE music_projects SET state='handed_off',handoff=? WHERE id=?", (json.dumps(handoff), name))
                self.store.event(db, "music_handoff_prepared", name, {"include_audio": include_audio, "remote_submitted": False})
        return self.inspect(name)

    def handoff_bytes(self, name):
        project = self.inspect(name)
        self.approved_plan(project)
        if not project["handoff"]:
            raise ValueError("Prepare the authorized handoff first")
        path = self.store.root/"music"/name/"handoff.zip"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != project["handoff"]["sha256"]:
            raise ValueError("Handoff artifact is missing or changed")
        return path.read_bytes()

    def external(self, name, reference, note):
        public_url(reference, suno=True)
        if not reference or not isinstance(note, str) or not 10 <= len(note.strip()) <= 2000:
            raise ValueError("Record the public Suno result reference and a meaningful operator note")
        with self.lock(name), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self.inspect(name)
            self.handoff_bytes(name)
            external = {"reference": reference, "note": note, "evidence": "operator-reported; not verified by a provider API"}
            if project["external"]:
                if project["external"] == external:
                    return project
                raise ValueError("External reference is immutable; create a new project for another attempt")
            db.execute("UPDATE music_projects SET state='external_reported',external=? WHERE id=?", (json.dumps(external), name))
            self.store.event(db, "music_external_reported", name, {"provider_verified": False})
        return self.inspect(name)

    def attach(self, name, asset_id, note):
        if not isinstance(note, str) or not 10 <= len(note.strip()) <= 2000:
            raise ValueError("Explain the adopted result in 10–2000 characters")
        with self.lock(name), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self.inspect(name)
            self.handoff_bytes(name)
            ref, _, payload = self.assets.reference({"asset": asset_id}, "audio")
            if not project["external"] or payload["origin"] != {"service": "suno", "reference": project["external"]["reference"]}:
                raise ValueError("Reviewed result origin must match the project's operator-reported Suno reference")
            if any(credit not in payload["attribution"] and credit != payload["license_url"] for credit in project["required_attributions"]):
                raise ValueError("Result attribution must preserve the declared lyric and reference credits")
            result = {"source": ref, "note": note, "evidence": "Local audio/hash/approval verified; remote generation remains operator-reported"}
            if project["result"]:
                if project["result"] == result:
                    return project
                raise ValueError("Adopted result is immutable; retain another attempt as a new project")
            db.execute("UPDATE music_projects SET state='result_attached',result=? WHERE id=?", (json.dumps(result), name))
            self.store.event(db, "music_result_attached", name, {"asset": asset_id, "provider_verified": False})
        return self.inspect(name)
