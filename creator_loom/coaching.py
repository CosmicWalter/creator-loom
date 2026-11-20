from __future__ import annotations

import json
import uuid
from pathlib import Path

from .domain import bounded, identifier
from .engine import digest


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
        return {"profile": profile, "dimensions": rows,
                "interpretation": "Self-reported revision results; no causal or independently verified learning claim"}
