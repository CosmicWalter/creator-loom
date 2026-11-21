from __future__ import annotations

import json
import io
import secrets
import zipfile
import uuid
from pathlib import Path

from .domain import bounded, identifier
from .engine import digest
from .assets import Assets


RUBRICS = {
    "text": {
        "clarity": "Can the intended reader explain the main idea after one reading?",
        "specificity": "Which abstract statement could be replaced with an observable example?",
        "structure": "Does each section serve the brief, with a clear progression?",
        "integrity": "Which factual statements need sources, and which passages are fictional?",
    },
    "image": {
        "hierarchy": "What catches attention first, and does that serve the brief?",
        "legibility": "Are title and focal subject readable at the intended display size?",
        "consistency": "Do palette, composition and references support the intended tone?",
        "integrity": "Are visual references licensed, and are any identities or marks misleading?",
    },
    "audio": {
        "intelligibility": "Can the audience understand every word at normal playback speed?",
        "pacing": "Where would a pause or shorter sentence improve comprehension?",
        "consistency": "Are voice, loudness and room tone consistent?",
        "integrity": "Is the voice authorized, and does the delivery preserve the text's meaning?",
    },
    "video": {
        "coherence": "Does the image support what is being said at each point?",
        "pacing": "Which section loses attention, and what specific edit would help?",
        "delivery": "Is framing, playback and audio appropriate for the destination?",
        "integrity": "Are all assets authorized and required AI disclosures present?",
    },
}


class Coach:
    """A grounded editorial exercise, not an automatic claim of user improvement."""

    def __init__(self, store, engine):
        self.store, self.engine = store, engine

    def workbook(self, run_id):
        run = self.store.run(run_id)
        if run["status"] not in {"needs_review", "approved"}:
            raise ValueError("Coaching requires finished artifacts")
        self.engine.verify_artifacts(run)
        stages = []
        for spec, step in zip(run["plan"]["steps"], run["steps"]):
            self.engine.artifact(run_id, step["result"])
            stages.append({"step": step["id"], "capability": spec["capability"],
                           "artifact": step["result"], "model": spec["model"]["id"],
                           "decision": spec["decision"], "rubric": RUBRICS[spec["capability"]]})
        result = {"run": run_id, "topic": run["brief"]["topic"], "stages": stages,
                  "exercise": ["Review one stage using one rubric dimension.",
                               "Save a revised artifact with one deliberate edit.",
                               "Score both versions with the same rubric and explain the evidence.",
                               "Record the revision with practice; compare repeated attempts over time."],
                  "measurement": "Human/self-reported assessments, not verified causal skill gains"}
        directory = self.store.root / "outputs" / run_id / "coaching"
        directory.mkdir(exist_ok=True)
        (directory / "workbook.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def record(self, run_id, step_id, revision: Path, dimension, before, after, rationale):
        bounded(before, 0, 1, "before")
        bounded(after, 0, 1, "after")
        run = self.store.run(run_id)
        if run["status"] not in {"needs_review", "approved"}:
            raise ValueError("Practice requires finished artifacts")
        spec = next((s for s in run["plan"]["steps"] if s["id"] == step_id), None)
        step = next((s for s in run["steps"] if s["id"] == step_id), None)
        if not spec or dimension not in RUBRICS[spec["capability"]]:
            raise ValueError("Choose an existing step and one of its rubric dimensions")
        self.engine.verify_artifacts(run)
        original = self.engine.artifact(run_id, step["result"])
        if not isinstance(rationale, str) or not 10 <= len(rationale.strip()) <= 4000:
            raise ValueError("Explain the edit and assessment in 10–4000 characters")
        revision = Path(revision)
        if not revision.is_file() or not 1 <= revision.stat().st_size <= 32 * 1024 * 1024:
            raise ValueError("Revision must be a nonempty file of at most 32 MB")
        raw = revision.read_bytes()
        if raw == original.read_bytes():
            raise ValueError("Practice requires a changed artifact")
        practice_id = uuid.uuid4().hex
        directory = self.store.root / "outputs" / run_id / "practice" / practice_id
        directory.mkdir(parents=True)
        # A fixed name avoids preserving identifying filenames or source paths.
        path = directory / "revision.bin"
        path.write_bytes(raw)
        artifact = {"file": str(path.relative_to(self.store.root / "outputs" / run_id)), "sha256": digest(path),
                    "original_sha256": step["result"]["sha256"]}
        with self.store.connect() as db:
            db.execute("INSERT INTO practice(id,profile,run_id,step_id,dimension,before_score,after_score,rationale,artifact) VALUES(?,?,?,?,?,?,?,?,?)",
                       (practice_id, run["brief"]["profile"], run_id, step_id, dimension, before, after,
                        rationale, json.dumps(artifact)))
            self.store.event(db, "practice", run_id, {"id": practice_id, "dimension": dimension})
        return {"practice": practice_id, "delta": after-before, "measurement": "human/self-reported", "artifact": artifact}

    def progress(self, profile):
        identifier(profile)
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT dimension,COUNT(*) AS attempts,AVG(after_score-before_score) AS mean_self_reported_delta FROM practice WHERE profile=? GROUP BY dimension", (profile,))]
        return {"profile": profile, "dimensions": rows, "blind_revision_reviews": self.blind_progress(profile),
                "interpretation": "Self-reported revision results; no causal or independently verified learning claim"}


    def practice(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM practice WHERE id=?", (name,)).fetchone()
        if not row:
            raise ValueError("Unknown practice revision")
        value = dict(row)
        value["artifact"] = json.loads(value["artifact"])
        return value

    def revision_pair(self, name):
        practice = self.practice(name)
        run = self.store.run(practice["run_id"])
        if run["status"] not in {"needs_review", "approved"}:
            raise ValueError("Practice source run is no longer reviewable")
        self.engine.verify_artifacts(run)
        spec = next(s for s in run["plan"]["steps"] if s["id"] == practice["step_id"])
        step = next(s for s in run["steps"] if s["id"] == practice["step_id"])
        if spec["capability"] != "text":
            raise ValueError("Blind practice review currently supports text revisions only")
        if practice["artifact"]["original_sha256"] != step["result"]["sha256"]:
            raise ValueError("Original revision binding changed")
        original = self.engine.artifact(run["id"], step["result"])
        revised = self.engine.artifact(run["id"], practice["artifact"])
        if max(original.stat().st_size, revised.stat().st_size) > 1024*1024:
            raise ValueError("Blind text revisions are limited to 1 MB each")
        for path in [original, revised]:
            try:
                value = path.read_text(encoding="utf-8")
            except UnicodeError:
                raise ValueError("Blind text revision must be UTF-8") from None
            if not value.strip() or "\0" in value:
                raise ValueError("Blind text revision must contain nonempty plain UTF-8 text")
        return practice, run, original, revised

    def new_review(self, practice_id):
        practice, run, original, revised = self.revision_pair(practice_id)
        binding = {"original": {"file": str(original.relative_to((self.store.root/"outputs"/run["id"]).resolve())), "sha256": digest(original)},
                   "revised": practice["artifact"], "dimension": practice["dimension"],
                   "brief": {k: run["brief"][k] for k in ["topic", "format", "language"]}}
        # Context needed for meaningful evaluation is shared, never the self scores.
        binding["credits"] = list(run["plan"].get("public_credits", [])) + [Assets(self.store).credits(ref["asset"]) for ref in run["plan"].get("input_assets", [])]
        binding["shared_inputs"] = []
        for dependency in next(s for s in run["plan"]["steps"] if s["id"] == practice["step_id"])["dependencies"]:
            step = next(s for s in run["steps"] if s["id"] == dependency)
            path = self.engine.artifact(run["id"], step["result"])
            if path.suffix == ".md" and path.stat().st_size <= 1024*1024:
                binding["shared_inputs"].append({"file": step["result"]["file"], "sha256": step["result"]["sha256"]})
        if run["plan"].get("context"):
            binding["brief"]["source_text"] = run["plan"]["context"]["source"]["text"]
            binding["brief"]["continuity"] = run["plan"]["context"]["continuity"]
            if run["plan"]["context"].get("character_memory"):
                from .story_memory import StoryMemory
                binding["brief"]["character_facts"] = StoryMemory.prompt_data(run["plan"]["context"]["character_memory"])
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT id FROM practice_reviews WHERE practice_id=?", (practice_id,)).fetchone()
            if prior:
                return self.review_inspect(prior["id"])
            order = ["original", "revised"]; secrets.SystemRandom().shuffle(order)
            review_id = uuid.uuid4().hex
            db.execute("INSERT INTO practice_reviews(id,practice_id,binding,display_order) VALUES(?,?,?,?)", (review_id, practice_id, json.dumps(binding), json.dumps(order)))
            self.store.event(db, "practice_blind_review_created", practice_id, {"review": review_id})
        return self.review_inspect(review_id)

    def review_load(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM practice_reviews WHERE id=?", (name,)).fetchone()
        if not row:
            raise ValueError("Unknown blind practice review")
        value = dict(row)
        for key in ["binding", "display_order", "scores"]:
            value[key] = json.loads(value[key]) if value[key] else None
        return value

    def verify_review(self, review):
        practice, run, original, revised = self.revision_pair(review["practice_id"])
        binding = review["binding"]
        if practice["dimension"] != binding["dimension"] or {k: run["brief"][k] for k in ["topic", "format", "language"]} != {k: binding["brief"][k] for k in ["topic", "format", "language"]}:
            raise ValueError("Practice review context changed")
        credits = list(run["plan"].get("public_credits", [])) + [Assets(self.store).credits(ref["asset"]) for ref in run["plan"].get("input_assets", [])]
        if binding["credits"] != credits:
            raise ValueError("Practice public credit context changed")
        context = run["plan"].get("context")
        if context and (binding["brief"].get("source_text") != context["source"]["text"] or binding["brief"].get("continuity") != context["continuity"]):
            raise ValueError("Practice source context changed")
        if context and context.get("character_memory"):
            from .story_memory import StoryMemory
            if binding["brief"].get("character_facts") != StoryMemory.prompt_data(context["character_memory"]):
                raise ValueError("Practice character context changed")
        if binding["revised"] != practice["artifact"] or binding["original"]["sha256"] != practice["artifact"]["original_sha256"]:
            raise ValueError("Practice review artifact binding changed")
        for result in [binding["original"], binding["revised"], *binding["shared_inputs"]]:
            self.engine.artifact(run["id"], result)
        return run

    def review_inspect(self, name):
        review = self.review_load(name)
        self.verify_review(review)
        return {"id": name, "practice": review["practice_id"], "dimension": review["binding"]["dimension"],
                "reviewed": review["scores"] is not None, "reviewer_kind": review["reviewer_kind"],
                "brief": review["binding"]["brief"], "rubric": RUBRICS["text"][review["binding"]["dimension"]],
                "blinding": "Presentation only; local owner can inspect mapping, content may reveal revision history"}

    def review_packet(self, name):
        review = self.review_load(name)
        run = self.verify_review(review)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            def write(filename, raw):
                info = zipfile.ZipInfo(filename, (1980, 1, 1, 0, 0, 0)); info.create_system = 0; info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, raw)
            for label, version in zip(["A", "B"], review["display_order"]):
                write(label+".txt", self.engine.artifact(run["id"], review["binding"][version]).read_bytes())
            for index, result in enumerate(review["binding"]["shared_inputs"], 1):
                write(f"shared/input-{index}.txt", self.engine.artifact(run["id"], result).read_bytes())
            write("review.json", json.dumps({"brief": review["binding"]["brief"], "dimension": review["binding"]["dimension"],
                "rubric": RUBRICS["text"][review["binding"]["dimension"]], "credits": review["binding"]["credits"], "scores": {"A": None, "B": None},
                "reviewer_kind": "self OR external-declared; no identity/independence verified", "rationale": ""}, ensure_ascii=False, indent=2).encode())
        return stream.getvalue()

    def score_review(self, name, scores, reviewer_kind, rationale):
        if not isinstance(scores, dict) or set(scores) != {"A", "B"}:
            raise ValueError("Provide exactly A/B scores")
        for score in scores.values(): bounded(score, 0, 1, "blind practice score")
        if reviewer_kind not in {"self", "external-declared"} or not isinstance(rationale, str) or not 10 <= len(rationale.strip()) <= 4000:
            raise ValueError("Declare self/external-declared review and a 10–4000 character rationale")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            review = self.review_load(name)
            self.verify_review(review)
            if review["scores"] is not None:
                raise ValueError("Blind review scores and reviewer declaration are immutable")
            db.execute("UPDATE practice_reviews SET scores=?,reviewer_kind=?,rationale=? WHERE id=?", (json.dumps(scores), reviewer_kind, rationale, name))
            self.store.event(db, "practice_blind_review_scored", review["practice_id"], {"review": name, "reviewer_kind": reviewer_kind})
        return self.review_report(name)

    def review_report(self, name):
        review = self.review_load(name)
        self.verify_review(review)
        if review["scores"] is None:
            raise ValueError("Record the blind comparison before revealing the revision mapping")
        scores = {version: review["scores"][label] for label, version in zip(["A", "B"], review["display_order"])}
        return {"id": name, "dimension": review["binding"]["dimension"], "scores": scores, "revision_delta": scores["revised"]-scores["original"],
                "reviewer_kind": review["reviewer_kind"], "rationale": review["rationale"],
                "interpretation": "Scored revision comparison only; external reviewer status is declared, not verified. No causal skill, transfer or durable learning claim."}

    def practice_list(self, profile):
        identifier(profile)
        with self.store.connect() as db:
            rows = db.execute("""SELECT p.id,p.dimension,p.run_id,p.step_id,p.created,r.id AS review_id,r.scores,r.reviewer_kind
              FROM practice p LEFT JOIN practice_reviews r ON r.practice_id=p.id WHERE p.profile=? ORDER BY p.rowid DESC LIMIT 100""", (profile,)).fetchall()
        return [{k: r[k] for k in ["id", "dimension", "run_id", "step_id", "created", "review_id", "reviewer_kind"]} | {"reviewed": r["scores"] is not None} for r in rows]

    def blind_progress(self, profile):
        with self.store.connect() as db:
            names = [r[0] for r in db.execute("""SELECT r.id FROM practice_reviews r JOIN practice p ON p.id=r.practice_id
              WHERE p.profile=? AND r.scores IS NOT NULL""", (profile,))]
        groups, invalid = {}, 0
        for name in names:
            try:
                report = self.review_report(name)
            except (ValueError, OSError):
                invalid += 1
                continue
            key = (report["dimension"], report["reviewer_kind"])
            groups.setdefault(key, []).append(report["revision_delta"])
        return {"dimensions": [{"dimension": dimension, "reviewer_kind": kind, "comparisons": len(values), "mean_revision_delta": sum(values)/len(values)} for (dimension, kind), values in sorted(groups.items())],
                "invalidated_comparisons": invalid, "interpretation": "Self and externally declared reviews are separate. Artifact-valid revision scores do not establish independent skill gains or transfer."}
