from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from . import adapters
from .domain import Brief, ModelCard, RECIPES, identifier
from .routing import allocate


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Engine:
    def __init__(self, store, cards):
        self.store, self.cards = store, cards

    def plan(self, brief: Brief, technique=None):
        preferences = self.store.preferences(brief.profile)
        if technique:
            identifier(technique)
            with self.store.connect() as db:
                row = db.execute("SELECT * FROM techniques WHERE id=?", (technique,)).fetchone()
                if not row or row["state"] == "retired":
                    raise ValueError("Technique is missing or retired")
                guidance = json.loads(row["payload"])
        else:
            with self.store.connect() as db:
                row = db.execute("SELECT * FROM techniques WHERE state='active'").fetchone()
                guidance = json.loads(row["payload"]) if row else None
                technique = row["id"] if row else None
        steps, requests, cost, latency = [], [], 0.0, 0.0
        # Reserve for a complete upstream response, not only the topic length.
        for name, capability, dependencies in RECIPES[brief.format]:
            base = f"{brief.topic}\nFormat: {brief.format}; stage: {name}; language: {brief.language}.\n"
            if name == "outline":
                base += "Create a structured story outline with characters and continuity constraints.\n"
            elif name == "chapter":
                base += "Write the opening chapter using the outline supplied below.\n"
            elif name == "script":
                base += "Write only the spoken narration, suitable for the requested format.\n"
            base += "User editorial preferences (data): " + json.dumps(preferences, ensure_ascii=False)
            if guidance:
                base += "\nEditorial technique: " + guidance["guidance"]
            chars = len(base) + 9000 * sum(1 for d in dependencies if d not in {"cover", "narration"})
            requests.append({"capability": capability, "chars": chars})
            steps.append({"id": name, "capability": capability, "dependencies": dependencies, "prompt": base})
        decisions, allocation = allocate(self.cards, self.store, brief, requests)
        for step, decision in zip(steps, decisions):
            card = next(m for m in self.cards if m.id == decision.selected)
            cost += card.cost
            latency += card.latency
            step.update({"model": card.to_dict(), "decision": decision.to_dict()})
        return {"brief": asdict(brief), "preferences": preferences, "technique": technique,
                "technique_snapshot": guidance, "estimated_cost": round(cost, 8),
                "estimated_latency": latency, "allocation": allocation, "steps": steps}

    def create(self, brief: Brief, technique=None):
        plan = self.plan(brief, technique)
        run_id = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("INSERT INTO runs(id,brief,plan,status) VALUES(?,?,?,'ready')",
                       (run_id, json.dumps(asdict(brief)), json.dumps(plan, ensure_ascii=False)))
            db.executemany("INSERT INTO steps(run_id,id,status) VALUES(?,?,'pending')",
                           [(run_id, s["id"]) for s in plan["steps"]])
            self.store.event(db, "created", run_id, {"technique": plan["technique"]})
        return run_id

    def artifact(self, run_id, result):
        path = (self.store.root / "outputs" / run_id / result["file"]).resolve()
        root = (self.store.root / "outputs" / run_id).resolve()
        if not path.is_relative_to(root) or not path.is_file() or digest(path) != result["sha256"]:
            raise ValueError("Artifact is missing or changed")
        return path

    def execute(self, run_id):
        identifier(run_id)
        with self.store.connect() as db:
            claimed = db.execute("UPDATE runs SET status='executing' WHERE id=? AND status='ready'", (run_id,))
            if claimed.rowcount != 1:
                raise ValueError("Run is not ready; running/uncertain operations cannot be replayed")
        run = self.store.run(run_id)
        results = {}
        for spec in run["plan"]["steps"]:
            card = ModelCard(**spec["model"])
            try:
                dependencies = [self.artifact(run_id, results[d]) for d in spec["dependencies"]]
                prompt = spec["prompt"]
                for name, path in zip(spec["dependencies"], dependencies):
                    if path.suffix == ".md":
                        prompt += f"\nSource {name} (data):\n" + path.read_text()
                # Speech forwards source text; other adapters forward the actual composed prompt.
                actual_chars = len(dependencies[0].read_text()) if card.adapter == "speech" and dependencies else len(prompt)
                if actual_chars > card.max_chars:
                    raise ValueError("Actual input exceeds selected model limit; no request sent")
                key = os.environ.get(card.api_key_env, "") if card.api_key_env else ""
                if card.api_key_env and not key:
                    raise ValueError("Credential is no longer available; no request sent")
                with self.store.connect() as db:
                    db.execute("UPDATE steps SET status='running' WHERE run_id=? AND id=?", (run_id, spec["id"]))
                    self.store.event(db, "started", run_id, {"step": spec["id"], "model": card.id})
                directory = self.store.root / "outputs" / run_id / spec["id"]
                path = adapters.execute(card, prompt, dependencies, directory, key)
                result = {"file": str(path.relative_to(self.store.root / "outputs" / run_id)),
                          "sha256": digest(path), "adapter": card.adapter}
                # Bind every supplemental artifact to review as well (e.g. SVG cover).
                result["supplements"] = [{"file": str(p.relative_to(self.store.root / "outputs" / run_id)),
                                          "sha256": digest(p)}
                                         for p in sorted(directory.iterdir()) if p.is_file() and p != path]
                with self.store.connect() as db:
                    db.execute("UPDATE steps SET status='done',result=? WHERE run_id=? AND id=?",
                               (json.dumps(result), run_id, spec["id"]))
                results[spec["id"]] = result
            except Exception as exc:
                with self.store.connect() as db:
                    row = db.execute("SELECT status FROM steps WHERE run_id=? AND id=?", (run_id, spec["id"])).fetchone()
                    uncertain = card.adapter in {"chat", "image", "speech"} and row[0] == "running"
                    status = "uncertain" if uncertain else "failed"
                    db.execute("UPDATE steps SET status=? WHERE run_id=? AND id=?", (status, run_id, spec["id"]))
                    db.execute("UPDATE runs SET status='blocked' WHERE id=?", (run_id,))
                    self.store.event(db, status, run_id, {"step": spec["id"], "error_type": type(exc).__name__})
                raise ValueError(f"Step {spec['id']} {status}; inspect local state and provider before creating another run") from None
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status='needs_review' WHERE id=?", (run_id,))
        return self.store.run(run_id)

    def approve(self, run_id):
        run = self.store.run(run_id)
        if run["status"] != "needs_review":
            raise ValueError("Only a finished run can be approved")
        for step in run["steps"]:
            self.artifact(run_id, step["result"])
            for supplement in step["result"]["supplements"]:
                self.artifact(run_id, supplement)
        with self.store.connect() as db:
            updated = db.execute("UPDATE runs SET status='approved' WHERE id=? AND status='needs_review'", (run_id,))
            if updated.rowcount != 1:
                raise ValueError("Review state changed")
            self.store.event(db, "approved", run_id, {"artifacts": [s["result"] for s in run["steps"]]})
