from __future__ import annotations

import json

from .domain import bounded, identifier, RECIPES
from . import evidence, editorial
from .feeds import discover, source_url


class Learning:
    def __init__(self, store, engine):
        self.store, self.engine = store, engine

    def propose(self, name, source, guidance):
        with self.store.connect() as db:
            self.propose_in(db, name, source, guidance)

    def propose_in(self, db, name, source, guidance, origin=None, task_scope=None):
        identifier(name)
        source_url(source)
        if not isinstance(guidance, str) or not 1 <= len(guidance.strip()) <= 2000:
            raise ValueError("Guidance must contain 1–2000 characters")
        if task_scope is not None:
            valid = {f"{fmt}:{step}" for fmt, recipe in RECIPES.items() for step, _, _ in recipe if fmt != "research"}
            if not isinstance(task_scope, list) or not task_scope or len(set(task_scope)) != len(task_scope) or any(t not in valid for t in task_scope):
                raise ValueError("Technique scope must name supported creative tasks")
        active = db.execute("SELECT id,payload FROM techniques WHERE state='active'").fetchone()
        payload = {"source": source, "guidance": guidance,
                   "baseline": active["id"] if active else None,
                   "baseline_snapshot": {"reference": active["id"], "sha256": evidence.digest(json.loads(active["payload"]))} if active else None}
        if task_scope is not None:
            payload["task_scope"] = task_scope
            base = json.loads(active["payload"]) if active else None
            payload["inherited_methods"] = {task: method for task in sorted(valid-set(task_scope))
                                             if (method := editorial.resolve(self.store, active["id"] if active else None, base, task)) is not None}
        if origin is not None:
            payload["origin"] = origin
        db.execute("INSERT INTO techniques(id,payload,state) VALUES(?,?,'proposed')", (name, json.dumps(payload)))
        self.store.event(db, "proposed", name, payload)

    def validate_origin(self, proposal):
        origin = proposal.get("origin", {})
        if origin.get("kind") != "reviewed_synthesis":
            return
        run = self.store.run(origin["run"])
        if run["status"] != "approved":
            raise ValueError("Synthesis artifact is no longer approved")
        self.engine.verify_artifacts(run)
        self.engine.artifact(run["id"], origin["artifact"])
        evidence.validate(self.store, origin["sources"])

    def validate_synthesis_pairs(self, proposal, pairs):
        origin = proposal.get("origin", {})
        if origin.get("kind") != "reviewed_synthesis":
            return
        with self.store.connect() as db:
            lab = db.execute("SELECT experiment_id FROM research_labs WHERE id=?", (origin["lab"],)).fetchone()
            trial = db.execute("SELECT state FROM benchmarks WHERE id=?", (lab["experiment_id"],)).fetchone() if lab else None
            cases = [dict(r) for r in db.execute("SELECT * FROM benchmark_cases WHERE benchmark_id=? ORDER BY id", (lab["experiment_id"],))] if lab else []
        if not trial or trial["state"] not in {"holdout", "reported"} or not cases or any(c["scores"] is None for c in cases):
            raise ValueError("Synthesis evaluation requires sealed development and complete immutable blind reviews")
        expected = []
        for case in cases:
            for arm in ["baseline", "candidate"]:
                run = self.store.run(case[arm+"_run"])
                if run["status"] not in {"needs_review", "approved"}:
                    raise ValueError("Experiment output is no longer reviewable")
                self.engine.verify_artifacts(run)
            if case["partition"] == "holdout":
                mapping = dict(zip(json.loads(case["display_order"]), ["A", "B"]))
                scores = json.loads(case["scores"])
                expected.append({"baseline": case["baseline_run"], "candidate": case["candidate_run"], "baseline_score": scores[mapping["baseline"]], "candidate_score": scores[mapping["candidate"]], "rationale": case["rationale"]})
        if any(not isinstance(p, dict) for p in pairs) or sorted(pairs, key=lambda p: p.get("baseline", "")) != sorted(expected, key=lambda p: p["baseline"]):
            raise ValueError("Synthesis evaluation must use exactly the recorded holdout pairs and scores")

    def evaluate(self, name, pairs):
        identifier(name)
        if not isinstance(pairs, list) or len(pairs) < 3:
            raise ValueError("At least three paired approved runs are required")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM techniques WHERE id=?", (name,)).fetchone()
            if not row or row["state"] not in {"proposed", "evaluated"}:
                raise ValueError("Only proposed or evaluated techniques can be evaluated")
            proposal = json.loads(row["payload"])
        self.validate_origin(proposal)
        self.validate_synthesis_pairs(proposal, pairs)
        topics, runs, deltas, bindings = set(), set(), [], []
        for pair in pairs:
            baseline, candidate = self.store.run(pair["baseline"]), self.store.run(pair["candidate"])
            if baseline["status"] != "approved" or candidate["status"] != "approved":
                raise ValueError("Evaluation requires human-approved outputs")
            if baseline["brief"] != candidate["brief"]:
                raise ValueError("Paired runs must have exactly the same brief")
            if candidate["plan"]["technique"] != name or baseline["plan"]["technique"] == name:
                raise ValueError("Candidate technique provenance mismatch")
            if (baseline["plan"]["technique"] != proposal["baseline"] or
                    baseline["plan"]["technique_snapshot"] != editorial.baseline(self.store, proposal) or
                    candidate["plan"]["technique_snapshot"] != proposal):
                raise ValueError("Evaluation does not match the proposal's frozen baseline")
            def context(plan):
                return {"preferences": plan["preferences"], "source_context": plan.get("context"), "input_assets": plan.get("input_assets", []), "public_credits": plan.get("public_credits", []), "research_context": plan.get("research_context"),
                        "steps": [{k: step[k] for k in ["id", "capability", "dependencies", "model"]}
                                  for step in plan["steps"]]}
            if context(baseline["plan"]) != context(candidate["plan"]):
                raise ValueError("Paired evaluation must freeze model and preference context, including source and continuity")
            topic = baseline["brief"]["topic"]
            if topic in topics or baseline["id"] in runs or candidate["id"] in runs:
                raise ValueError("Evaluation needs distinct topics and run pairs")
            topics.add(topic)
            runs.update([baseline["id"], candidate["id"]])
            for run in [baseline, candidate]:
                self.engine.verify_artifacts(run)
                bindings.append({"run": run["id"], "results": [s["result"] for s in run["steps"]]})
            a = bounded(pair["baseline_score"], 0, 1, "baseline_score")
            b = bounded(pair["candidate_score"], 0, 1, "candidate_score")
            if not isinstance(pair.get("rationale"), str) or len(pair["rationale"].strip()) < 10:
                raise ValueError("Each pair requires a review rationale of at least ten characters")
            deltas.append(b - a)
        mean = sum(deltas) / len(deltas)
        result = {"mean_delta": mean, "worst_delta": min(deltas), "pairs": pairs,
                  "bindings": bindings, "passed": mean >= 0.05 - 1e-9 and min(deltas) >= -0.1 - 1e-9,
                  "proposal": proposal, "method": "human-scored paired evaluation; not statistical proof"}
        with self.store.connect() as db:
            row = db.execute("SELECT state FROM techniques WHERE id=?", (name,)).fetchone()
            if not row or row[0] not in {"proposed", "evaluated"}:
                raise ValueError("Only proposed or evaluated techniques can be evaluated")
            db.execute("UPDATE techniques SET evaluation=?,state='evaluated' WHERE id=?", (json.dumps(result), name))
            self.store.event(db, "evaluated", name, result)
        return result

    def promote(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM techniques WHERE id=?", (name,)).fetchone()
            if not row or row["state"] != "evaluated" or not row["evaluation"]:
                raise ValueError("Technique must be evaluated before activation")
            evaluation = json.loads(row["evaluation"])
            self.validate_origin(evaluation["proposal"])
            self.validate_synthesis_pairs(evaluation["proposal"], evaluation["pairs"])
            if evaluation["proposal"] != json.loads(row["payload"]):
                raise ValueError("Proposal changed after evaluation")
            if not evaluation["passed"]:
                raise ValueError("Evaluation did not pass")
            for binding in evaluation["bindings"]:
                bound_run = self.store.run(binding["run"])
                if bound_run["status"] != "approved":
                    raise ValueError("Evaluated run is no longer approved")
                self.engine.verify_artifacts(bound_run)
                for result in binding["results"]:
                    self.engine.artifact(binding["run"], result)
                    for supplement in result["supplements"]:
                        self.engine.artifact(binding["run"], supplement)
            previous = db.execute("SELECT id,payload FROM techniques WHERE state='active'").fetchone()
            if (previous[0] if previous else None) != evaluation["proposal"]["baseline"] or (json.loads(previous["payload"]) if previous else None) != editorial.baseline(self.store, evaluation["proposal"]):
                raise ValueError("Active baseline changed; evaluate a new proposal against the current baseline")
            db.execute("UPDATE techniques SET state='retired' WHERE state='active'")
            db.execute("UPDATE techniques SET state='active',previous_state=? WHERE id=?",
                       (previous[0] if previous else None, name))
            self.store.event(db, "promoted", name, {"previous": previous[0] if previous else None})

    def rollback(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM techniques WHERE id=? AND state='active'", (name,)).fetchone()
            if not row:
                raise ValueError("Only the active technique can be rolled back")
            db.execute("UPDATE techniques SET state='retired' WHERE id=?", (name,))
            if row["previous_state"]:
                db.execute("UPDATE techniques SET state='active' WHERE id=?", (row["previous_state"],))
            self.store.event(db, "rolled_back", name, {"restored": row["previous_state"]})
