"""Synthetic feed/model/review fixtures test learning gates, not quality gains."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.lab import Lab
from creator_loom.learning import Learning
from creator_loom.research import Research
from creator_loom.store import Store


class LabTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.cards = [ModelCard("writer", "text", "chat", model="fixture", endpoint="http://127.0.0.1:8765/v1", local=True, max_chars=40000)]
        self.engine = Engine(self.store, self.cards)
        self.learning = Learning(self.store, self.engine)
        self.entries = [{"title": "Original synthetic editorial note", "summary": "Use concrete sensory details to improve editorial clarity in short fiction.", "source": "https://example.com/editorial", "published": "2026-11-21"}]
        self.research = Research(self.store, self.learning, lambda _: copy.deepcopy(self.entries))
        self.research.subscribe("fixture", "https://github.com/Comfy-Org/ComfyUI/releases.atom", [])
        self.research.refresh("fixture")
        self.item = self.research.inbox()[0]
        self.lab = Lab(self.store, self.cards)
        self.calls = []
        self.value = self.output()
        patcher = patch.object(adapters, "execute", self.writer); patcher.start(); self.addCleanup(patcher.stop)
        self.review = {"note": "Read the original synthetic evidence and reviewed the limited inference.", "license_review": "Original synthetic text; no external code/assets are imported.", "compatibility_review": "Editorial-only instruction; no adapter or permission changes.", "cases_authorized": True}
        self.settings = {"total_budget": 1, "local_only": True, "max_latency": 300}

    def output(self):
        return {"status": "propose", "task": "novel:chapter", "title": "Concrete sensory anchors", "hypothesis": "Concrete details may improve chapter clarity; this is an untested hypothesis.",
                "guidance": "Use one concrete sensory anchor per scene and remove ungrounded ornamental claims.",
                "citations": [{"item": self.item["id"], "revision": 1, "quote": self.entries[0]["summary"], "supports": "The summary suggests concrete details; it does not measure their effect."}],
                "license_caution": "Original fixture only. Real source permissions still need human review.", "compatibility": "editorial-only", "limitations": "Feed summary only, not a full paper or actual quality evidence.", "cases": [f"Original fictional lighthouse scene {i}, written for a new test." for i in range(6)]}

    def writer(self, card, prompt, dependencies, directory, key=""):
        self.calls.append(prompt)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/"content.md"
        path.write_text(json.dumps(self.value) if "Format: research;" in prompt else "Synthetic creative fixture: "+str(len(self.calls)))
        return path

    def create(self, name="trial"):
        return self.lab.create(name, {"task": "novel:chapter", "sources": [{"item": self.item["id"], "revision": self.item["revision"]}], "goal": "Investigate a constrained editorial method for fictional chapter clarity."}, request_key=name+"-request")

    def synthesize(self):
        lab = self.create()
        self.engine.execute(lab["run_id"]); self.engine.approve(lab["run_id"])
        return lab

    def accepted(self):
        self.synthesize()
        return self.lab.accept("trial", "sensory", self.review)

    def finish(self):
        self.accepted()
        experiment = self.lab.experiment("trial", self.settings)
        for partition in ["development", "holdout"]:
            for case in experiment["cases"]:
                if case["partition"] != partition:
                    continue
                for arm in ["baseline", "candidate"]:
                    self.lab.benchmarks.generate(experiment["id"], case["id"], arm)
                raw = next(c for c in self.lab.benchmarks._load(experiment["id"])["cases"] if c["id"] == case["id"])
                # Development deliberately prefers baseline; only holdout can activate.
                scores = {label: (0.8 if arm == ("candidate" if partition == "holdout" else "baseline") else 0.5) for label, arm in zip(["A", "B"], json.loads(raw["display_order"]))}
                self.lab.benchmarks.review(experiment["id"], case["id"], scores, "Synthetic scores verify partition isolation, not a real creative gain.")
                for arm in ["baseline", "candidate"]:
                    self.engine.approve(case[arm+"_run"])
            if partition == "development":
                self.lab.benchmarks.seal_development(experiment["id"])
        return experiment

    def test_frozen_evidence_and_no_active_instruction_in_synthesis(self):
        self.learning.propose("old", "https://example.com/method", "Old editorial instruction must not bias source synthesis.")
        with self.store.connect() as db:
            db.execute("UPDATE techniques SET state='active' WHERE id='old'")
        lab = self.create()
        run = self.store.run(lab["run_id"])
        self.assertIsNone(run["plan"]["technique"])
        self.assertNotIn("Old editorial instruction", run["plan"]["steps"][0]["prompt"])
        self.assertEqual(run["plan"]["research_context"]["sources"][0]["sha256"], self.item["sha256"])
        self.assertEqual(self.create()["run_id"], lab["run_id"])
        self.assertEqual(lab["protocol"]["baseline"]["id"], "old")

    def test_quote_fabrication_wrong_revision_and_executable_schema_are_rejected(self):
        lab = self.create()
        for change in ["fabrication", "revision", "compatibility", "cases", "unknown-field"]:
            value = copy.deepcopy(self.output())
            if change == "fabrication": value["citations"][0]["quote"] = "A quotation that is not present in the selected source."
            if change == "revision": value["citations"][0]["revision"] = 2
            if change == "compatibility": value["compatibility"] = "execute-code"
            if change == "cases": value["cases"][1] = value["cases"][0]
            if change == "unknown-field": value["commands"] = ["untrusted"]
            with self.store.connect() as db:
                run = self.store.run(lab["run_id"])
                db.execute("UPDATE runs SET status='ready' WHERE id=?", (run["id"],))
                db.execute("UPDATE steps SET status='pending',result=NULL WHERE run_id=?", (run["id"],))
                db.execute("DELETE FROM measurements WHERE run_id=?", (run["id"],))
            self.value = value; self.engine.execute(lab["run_id"])
            with self.assertRaises(ValueError): self.lab.draft("trial")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM techniques").fetchone()[0], 0)

    def test_insufficient_evidence_is_a_valid_non_proposal(self):
        self.value = {"status": "insufficient", "task": "novel:chapter", "reason": "This source has no measured or actionable support for a new method."}
        self.synthesize()
        self.assertEqual(self.lab.draft("trial")["status"], "insufficient")
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            self.lab.accept("trial", "sensory", self.review)

    def test_review_permissions_and_current_evidence_are_required(self):
        lab = self.create(); self.engine.execute(lab["run_id"])
        with self.assertRaisesRegex(ValueError, "Approve"):
            self.lab.accept("trial", "sensory", self.review)
        self.engine.approve(lab["run_id"])
        bad = {**self.review, "cases_authorized": False}
        with self.assertRaises(ValueError): self.lab.accept("trial", "sensory", bad)
        self.entries[0]["summary"] += " New evidence revision."
        self.research.refresh("fixture")
        self.assertTrue(self.lab.inspect("trial")["evidence_stale"])
        with self.assertRaisesRegex(ValueError, "Evidence changed"):
            self.lab.accept("trial", "sensory", self.review)

    def test_baseline_change_blocks_acceptance(self):
        self.synthesize()
        self.learning.propose("other", "https://example.com/method", "A later human-approved baseline fixture.")
        with self.store.connect() as db: db.execute("UPDATE techniques SET state='active' WHERE id='other'")
        with self.assertRaisesRegex(ValueError, "baseline changed"):
            self.lab.accept("trial", "sensory", self.review)

    def test_acceptance_is_immutable_and_does_not_activate(self):
        accepted = self.accepted()
        self.assertEqual(accepted["technique_state"], "proposed")
        self.lab.accept("trial", "sensory", self.review)
        with self.assertRaises(ValueError): self.learning.promote("sensory")
        with self.assertRaises(ValueError): self.lab.accept("trial", "renamed", self.review)
        with self.store.connect() as db:
            payload = json.loads(db.execute("SELECT payload FROM techniques WHERE id='sensory'").fetchone()[0])
        self.assertEqual(payload["task_scope"], ["novel:chapter"])
        self.assertEqual(payload["origin"]["sources"][0]["revision"], 1)

    def test_heldout_experiment_reuses_prefix_and_does_not_calibrate_models(self):
        experiment = self.finish()
        self.assertEqual(self.lab.experiment("trial", self.settings)["id"], experiment["id"])
        self.assertEqual(len(self.calls), 19)  # one synthesis plus six times (outline + two chapters)
        result = self.lab.evaluate("trial")
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["pairs"]), 3)
        self.assertAlmostEqual(result["mean_delta"], 0.3)
        with self.assertRaisesRegex(ValueError, "cannot calibrate"):
            self.lab.benchmarks.calibrate(experiment["id"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)
        self.learning.promote("sensory")
        novel = self.engine.plan(Brief("Original future story", "novel"))
        self.assertIsNone(novel["steps"][0]["editorial_technique"])
        self.assertEqual(novel["steps"][1]["editorial_technique"], "sensory")
        self.assertIsNone(self.engine.plan(Brief("Original article"))["steps"][0]["editorial_technique"])
        self.learning.rollback("sensory")

    def test_scoped_method_inherits_reviewed_baseline_for_other_steps(self):
        self.learning.propose("old", "https://example.com/method", "Maintain the existing editorial baseline outside the changed task.")
        with self.store.connect() as db: db.execute("UPDATE techniques SET state='active' WHERE id='old'")
        self.finish(); self.lab.evaluate("trial"); self.learning.promote("sensory")
        plan = self.engine.plan(Brief("Original future story", "novel"))
        self.assertEqual([s["editorial_technique"] for s in plan["steps"]], ["old", "sensory"])
        self.assertEqual(self.engine.plan(Brief("Original article"))["steps"][0]["editorial_technique"], "old")
        self.learning.rollback("sensory")
        self.assertEqual(self.engine.plan(Brief("Original future story", "novel"))["steps"][1]["editorial_technique"], "old")

    def test_synthesis_artifact_tampering_blocks_promotion_after_successful_evaluation(self):
        self.finish(); self.lab.evaluate("trial")
        run = self.store.run(self.lab.load("trial")["run_id"])
        self.engine.artifact(run["id"], run["steps"][0]["result"]).write_text("Changed synthesis")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.learning.promote("sensory")
        with self.assertRaises(ValueError): self.lab.evaluate("trial")

    def test_repeated_scoped_updates_keep_flat_planning_snapshots(self):
        for i in range(40):
            name = f"method-{i}"
            with self.store.connect() as db:
                self.learning.propose_in(db, name, "https://example.com/editorial", f"Original editorial instruction iteration {i}.", task_scope=["novel:chapter"])
                db.execute("UPDATE techniques SET state='retired' WHERE state='active'")
                db.execute("UPDATE techniques SET state='active' WHERE id=?", (name,))
        plan = self.engine.plan(Brief("Original future story", "novel"))
        self.assertEqual([s["editorial_technique"] for s in plan["steps"]], [None, "method-39"])
        self.assertLess(len(json.dumps(plan["technique_snapshot"])), 1500)
        self.assertIn("reference", plan["technique_snapshot"]["baseline_snapshot"])

    def test_general_learning_api_cannot_replace_locked_holdout_scores(self):
        self.finish()
        lab = self.lab.load("trial")
        report = self.lab.benchmarks.report(lab["experiment_id"])
        trial = self.lab.benchmarks._load(lab["experiment_id"])
        dev = [c for c in trial["cases"] if c["partition"] == "development"]
        forged = [{"baseline": c["baseline_run"], "candidate": c["candidate_run"], "baseline_score": 0, "candidate_score": 1, "rationale": "Forged development scores must not bypass the holdout protocol."} for c in dev]
        with self.assertRaisesRegex(ValueError, "recorded holdout"):
            self.learning.evaluate("sensory", forged)
        accepted = self.lab.evaluate("trial")
        retuned = copy.deepcopy(accepted["pairs"]); retuned[0]["candidate_score"] = 1
        with self.assertRaisesRegex(ValueError, "recorded holdout"):
            self.learning.evaluate("sensory", retuned)
        self.assertTrue(accepted["passed"])


    def test_rollback_remains_available_after_source_output_loss(self):
        self.finish(); self.lab.evaluate("trial"); self.lab.activate("trial")
        run = self.store.run(self.lab.load("trial")["run_id"])
        self.engine.artifact(run["id"], run["steps"][0]["result"]).unlink()
        self.lab.activate("trial", rollback=True)
        self.assertIsNone(self.engine.plan(Brief("Original future story", "novel"))["technique"])
