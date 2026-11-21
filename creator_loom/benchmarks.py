"""Task-isolated model comparisons with sealed presentation and held-out cases."""

from __future__ import annotations

import io
import json
import math
import secrets
import shutil
import uuid
import zipfile

from .domain import Brief, RECIPES, bounded, identifier
from .engine import Engine
from .library import Library
from .locking import run_lock


class Benchmarks:
    def __init__(self, store, cards):
        self.store, self.cards = store, cards
        self.engine = Engine(store, cards)

    def create(self, name, spec):
        identifier(name)
        if not isinstance(spec, dict) or set(spec) != {"task", "baseline_model", "candidate_model", "cases"}:
            raise ValueError("Benchmark spec needs task, baseline_model, candidate_model and cases")
        task = spec["task"]
        valid = {f"{fmt}:{step}": (fmt, step) for fmt, recipe in RECIPES.items() for step, _, _ in recipe}
        if task not in valid:
            raise ValueError("Unknown benchmark task")
        if spec["baseline_model"] == spec["candidate_model"]:
            raise ValueError("Compare two distinct model IDs")
        for key in ["baseline_model", "candidate_model"]:
            identifier(spec[key])
            if spec[key] not in {m.id for m in self.cards}:
                raise ValueError("Benchmark model not found in the configured catalog")
        if not isinstance(spec["cases"], list) or not 6 <= len(spec["cases"]) <= 50:
            raise ValueError("A benchmark requires 6–50 distinct cases")
        fmt, target = valid[task]
        case_ids, topics, profiles, plans = set(), set(), set(), []
        for case in spec["cases"]:
            if not isinstance(case, dict) or not {"id", "brief"} <= set(case) or set(case) - {"id", "brief", "book", "unit", "continuity"}:
                raise ValueError("Case needs id, brief and optional book, unit, continuity")
            if not case.get("book") and (case.get("unit", 0) != 0 or case.get("continuity")):
                raise ValueError("Unit and continuity require an imported book")
            identifier(case["id"])
            brief = Brief(**case["brief"])
            topic = " ".join(brief.topic.casefold().split())
            if case["id"] in case_ids or topic in topics or brief.format != fmt:
                raise ValueError("Cases need distinct IDs/topics and the task's format")
            case_ids.add(case["id"]); topics.add(topic); profiles.add(brief.profile)
            context = Library(self.store).context(case["book"], case.get("unit", 0), case.get("continuity", "")) if case.get("book") else None
            base = self.engine.plan(brief, context=context, model_overrides={target: spec["baseline_model"]}, stop_after=target)
            fixed = {s["id"]: s["model"]["id"] for s in base["steps"]}
            fixed[target] = spec["candidate_model"]
            candidate = self.engine.plan(brief, context=context, model_overrides=fixed, stop_after=target)
            if any(base[k] != candidate[k] for k in ["preferences", "context", "technique", "technique_snapshot"]):
                raise ValueError("Context changed during benchmark planning; retry with a stable configuration")
            if any(a["model"] != b["model"] for a, b in zip(base["steps"][:-1], candidate["steps"][:-1])):
                raise ValueError("Non-target model context changed during planning")
            plans.append((case["id"], base, candidate))
        if len(profiles) != 1:
            raise ValueError("Benchmark cases must share a profile")
        protocol = {"task": task, "target": target, "baseline_model": spec["baseline_model"],
                    "candidate_model": spec["candidate_model"], "profile": next(iter(profiles)),
                    "method": "shared upstream artifacts; randomized A/B presentation; preassigned development/holdout split",
                    "cost_caveat": "Conservative full-plan sum; candidate upstream is reused. Not invoices or a budget-matched experiment.",
                    "planned_cost_estimate": sum(p["estimated_cost"] for _, a, b in plans for p in [a, b])}
        protocol["kind"] = "model"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.persist_in(db, name, plans, protocol)
        return self.inspect(name)

    def persist_in(self, db, name, plans, protocol):
        identifier(name)
        # Split and presentation mapping are committed before any generation.
        shuffled = [case_id for case_id, _, _ in plans]
        secrets.SystemRandom().shuffle(shuffled)
        development = set(shuffled[:len(shuffled)//2])
        db.execute("INSERT INTO benchmarks(id,protocol,state) VALUES(?,?,'development')", (name, json.dumps(protocol)))
        for case_id, baseline, candidate in plans:
            base_id, cand_id = uuid.uuid4().hex, uuid.uuid4().hex
            for arm, run_id, plan in [("baseline", base_id, baseline), ("candidate", cand_id, candidate)]:
                plan["benchmark"] = {"id": name, "case": case_id, "arm": arm, "target": protocol["target"]}
                self.engine.persist(db, run_id, plan)
            order = ["baseline", "candidate"]
            secrets.SystemRandom().shuffle(order)
            db.execute("INSERT INTO benchmark_cases(benchmark_id,id,partition,baseline_run,candidate_run,display_order) VALUES(?,?,?,?,?,?)",
                       (name, case_id, "development" if case_id in development else "holdout", base_id, cand_id, json.dumps(order)))
        self.store.event(db, "benchmark_created", name, {"task": protocol["task"], "cases": len(plans), "kind": protocol.get("kind", "model")})

    def _load(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM benchmarks WHERE id=?", (name,)).fetchone()
            cases = [dict(r) for r in db.execute("SELECT * FROM benchmark_cases WHERE benchmark_id=? ORDER BY id", (name,))]
        if not row:
            raise ValueError("Unknown benchmark")
        return {**dict(row), "protocol": json.loads(row["protocol"]), "cases": cases}

    def inspect(self, name):
        trial = self._load(name)
        # Operator view shows generation handles, but not the A/B display mapping.
        return {"id": name, "state": trial["state"], "protocol": trial["protocol"],
                "cases": [{k: c[k] for k in ["id", "partition", "baseline_run", "candidate_run"]} |
                          {"reviewed": c["scores"] is not None} for c in trial["cases"]]}

    @staticmethod
    def accessible(trial, case):
        if case["partition"] == "holdout" and trial["state"] == "development":
            raise ValueError("Holdout generation/review is locked until development reviews are sealed")

    def generate(self, name, case_id, arm):
        trial = self._load(name)
        case = next((c for c in trial["cases"] if c["id"] == case_id), None)
        if not case or arm not in {"baseline", "candidate"} or trial["state"] not in {"development", "holdout"}:
            raise ValueError("Unknown case/arm or benchmark is already closed")
        self.accessible(trial, case)
        run_id = case[arm+"_run"]
        with run_lock(self.store, run_id):
            run = self.store.run(run_id)
            if run["status"] != "ready":
                # A duplicate command never creates another inference run.
                return {"run": run_id, "status": run["status"], "submitted": False}
            if arm == "candidate" and len(run["steps"]) > 1:
                baseline = self.store.run(case["baseline_run"])
                if baseline["status"] not in {"needs_review", "approved"}:
                    raise ValueError("Generate the baseline first so upstream artifacts can be shared")
                self.engine.verify_artifacts(baseline)
                copied = []
                for step in baseline["steps"][:-1]:
                    # Candidate generation uses the identical creative inputs,
                    # not another stochastic run of the same upstream model.
                    result = json.loads(json.dumps(step["result"]))
                    for file in [result, *result["supplements"]]:
                        original = self.engine.artifact(baseline["id"], file)
                        root = (self.store.root/"outputs"/run_id).resolve()
                        target = (root/file["file"]).resolve()
                        if not target.is_relative_to(root):
                            raise ValueError("Reused artifact escapes its output directory")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(original, target)
                    result["reused_from"] = {"run": baseline["id"], "step": step["id"]}
                    copied.append((json.dumps(result), run_id, step["id"]))
                with self.store.connect() as db:
                    db.executemany("UPDATE steps SET result=?,status='done' WHERE run_id=? AND id=?", copied)
            result = self.engine._drive(run_id, resume=False, benchmark=True)
        return {"run": run_id, "status": result["status"], "submitted": True}

    def _case(self, trial, case_id):
        case = next((c for c in trial["cases"] if c["id"] == case_id), None)
        if not case:
            raise ValueError("Unknown benchmark case")
        self.accessible(trial, case)
        for arm in ["baseline", "candidate"]:
            run = self.store.run(case[arm+"_run"])
            if run["status"] not in {"needs_review", "approved"}:
                raise ValueError("Both creative outputs must finish before review")
            self.engine.verify_artifacts(run)
        return case

    def packet(self, name, case_id):
        trial = self._load(name)
        case = self._case(trial, case_id)
        baseline = self.store.run(case["baseline_run"])
        brief = baseline["brief"]
        context = baseline["plan"].get("context")
        result = {"case": case_id, "brief": {k: brief[k] for k in ["topic", "format", "language"]},
                  "task": trial["protocol"]["task"], "outputs": {}, "shared_inputs": {}}
        if context:
            result["brief"]["source_text"] = context["source"]["text"]
            result["brief"]["continuity"] = context["continuity"]
        target = baseline["plan"]["steps"][-1]
        for step in baseline["steps"][:-1]:
            if step["id"] not in target["dependencies"]:
                continue
            artifact = self.engine.artifact(baseline["id"], step["result"])
            result["shared_inputs"][step["id"]+artifact.suffix] = artifact.read_bytes()
        for label, arm in zip(["A", "B"], json.loads(case["display_order"])):
            run = self.store.run(case[arm+"_run"])
            step = run["steps"][-1]
            artifact = self.engine.artifact(run["id"], step["result"])
            # Only the target creative file is presented, never run/model IDs,
            # usage, scores, timing or request receipts.
            result["outputs"][label] = {"bytes": artifact.read_bytes(), "suffix": artifact.suffix}
        return result

    def packet_bytes(self, name, case_id):
        packet = self.packet(name, case_id)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for label, output in packet["outputs"].items():
                info = zipfile.ZipInfo(label+output["suffix"], (1980, 1, 1, 0, 0, 0))
                info.create_system = 0
                archive.writestr(info, output["bytes"])
            for filename, raw in packet["shared_inputs"].items():
                info = zipfile.ZipInfo("shared/"+filename, (1980, 1, 1, 0, 0, 0))
                info.create_system = 0
                archive.writestr(info, raw)
            info = zipfile.ZipInfo("review.json", (1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            archive.writestr(info, json.dumps({"case": case_id, "task": packet["task"], "brief": packet["brief"],
                "rubric": "Score fitness to the brief, clarity and medium-specific craft consistently, 0–1.",
                "shared_inputs": list(packet["shared_inputs"]),
                "scores": {"A": None, "B": None}, "rationale": ""}, ensure_ascii=False, indent=2))
        return stream.getvalue()

    def write_packet(self, name, case_id):
        raw = self.packet_bytes(name, case_id)
        directory = self.store.root/"benchmark_packets"/name
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/(case_id+".zip")
        path.write_bytes(raw)
        return {"packet": str(path), "labels": ["A", "B"], "model_mapping_included": False}

    def target_artifact(self, name, case_id, label):
        if label not in {"A", "B"}:
            raise ValueError("Blind output label must be A or B")
        trial = self._load(name)
        case = self._case(trial, case_id)
        arm = json.loads(case["display_order"])[["A", "B"].index(label)]
        run = self.store.run(case[arm+"_run"])
        return self.engine.artifact(run["id"], run["steps"][-1]["result"])

    def review(self, name, case_id, scores, rationale):
        if not isinstance(scores, dict) or set(scores) != {"A", "B"}:
            raise ValueError("Provide exactly A and B scores")
        for score in scores.values():
            bounded(score, 0, 1, "blind score")
        if not isinstance(rationale, str) or not 10 <= len(rationale.strip()) <= 4000:
            raise ValueError("Explain the comparative review in 10–4000 characters")
        trial = self._load(name)
        self._case(trial, case_id)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state FROM benchmarks WHERE id=?", (name,)).fetchone()[0]
            if current not in {"development", "holdout"}:
                raise ValueError("Benchmark reviews are closed")
            row = db.execute("SELECT * FROM benchmark_cases WHERE benchmark_id=? AND id=?", (name, case_id)).fetchone()
            if row["partition"] == "development" and current != "development":
                raise ValueError("Development reviews are sealed")
            if row["partition"] == "holdout" and current != "holdout":
                raise ValueError("Holdout review is not open")
            if row["scores"] is not None:
                raise ValueError("Review is already recorded; scores cannot be retuned")
            db.execute("UPDATE benchmark_cases SET scores=?,rationale=? WHERE benchmark_id=? AND id=?",
                       (json.dumps(scores), rationale, name, case_id))
            self.store.event(db, "blind_review", name, {"case": case_id, "partition": row["partition"]})
        return {"case": case_id, "recorded": True}

    def seal_development(self, name):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM benchmarks WHERE id=?", (name,)).fetchone()
            missing = db.execute("SELECT COUNT(*) FROM benchmark_cases WHERE benchmark_id=? AND partition='development' AND scores IS NULL", (name,)).fetchone()[0]
            if not row or row[0] != "development" or missing:
                raise ValueError("Finish all development reviews before sealing")
            db.execute("UPDATE benchmarks SET state='holdout' WHERE id=?", (name,))
            self.store.event(db, "development_sealed", name, {})
        return self.inspect(name)

    def report(self, name):
        trial = self._load(name)
        if trial["state"] not in {"holdout", "reported", "calibrated"} or any(c["scores"] is None for c in trial["cases"]):
            raise ValueError("Complete sealed development and all holdout reviews before reporting")
        partitions = {}
        for partition in ["development", "holdout"]:
            pairs = []
            for case in trial["cases"]:
                if case["partition"] != partition:
                    continue
                self._case(trial, case["id"])
                mapping = dict(zip(json.loads(case["display_order"]), ["A", "B"]))
                raw = json.loads(case["scores"])
                a, b = raw[mapping["baseline"]], raw[mapping["candidate"]]
                pairs.append({"case": case["id"], "baseline": a, "candidate": b, "delta": b-a,
                              "rationale": case["rationale"]})
            wins = sum(p["delta"] > 0 for p in pairs)
            losses = sum(p["delta"] < 0 for p in pairs)
            n = wins+losses
            partitions[partition] = {"n": len(pairs), "mean_delta": sum(p["delta"] for p in pairs)/len(pairs),
                "wins": wins, "losses": losses, "ties": len(pairs)-n,
                "one_sided_sign_test_p": sum(math.comb(n, k) for k in range(wins, n+1))/2**n if n else 1,
                "pairs": pairs}
        result = {"protocol": trial["protocol"], "partitions": partitions,
                  "interpretation": "Human-scored presentation-blinded comparisons, not proof of population quality or reviewer independence"}
        with self.store.connect() as db:
            db.execute("UPDATE benchmarks SET report=?,state=CASE WHEN state='calibrated' THEN state ELSE 'reported' END WHERE id=?",
                       (json.dumps(result), name))
        return result

    def calibrate(self, name):
        if self._load(name)["protocol"].get("kind", "model") != "model":
            raise ValueError("Technique experiments cannot calibrate model quality feedback")
        result = self.report(name)
        trial = self._load(name)
        # Only the reserved holdout observations enter routing feedback, after
        # explicit normal artifact approval. Development remains exploratory.
        rows = []
        for case in trial["cases"]:
            if case["partition"] != "holdout":
                continue
            mapping = dict(zip(json.loads(case["display_order"]), ["A", "B"]))
            scores = json.loads(case["scores"])
            for arm in ["baseline", "candidate"]:
                run_id = case[arm+"_run"]
                run = self.store.run(run_id)
                if run["status"] != "approved":
                    raise ValueError("Approve holdout artifacts before using scores for routing calibration")
                self.engine.verify_artifacts(run)
                step = run["plan"]["steps"][-1]
                rows.append((run_id, trial["protocol"]["target"], trial["protocol"]["profile"],
                             step["capability"], step["model"]["id"], scores[mapping[arm]]))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in rows:
                db.execute('''INSERT INTO feedback VALUES(?,?,?,?,?,?)
                  ON CONFLICT(run_id,step_id) DO UPDATE SET rating=excluded.rating''',
                           row)
            db.execute("UPDATE benchmarks SET state='calibrated' WHERE id=?", (name,))
            self.store.event(db, "benchmark_calibrated", name, {"holdout_feedback": len(rows)})
        return {"state": "calibrated", "holdout_feedback": len(rows), "report": result}
