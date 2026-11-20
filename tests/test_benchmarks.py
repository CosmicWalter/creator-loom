"""Synthetic outputs and ratings test protocol mechanics, never model quality."""

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.benchmarks import Benchmarks
from creator_loom.cli import main
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.library import Library
from creator_loom.store import Store


class BenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"state")
        self.cards = [ModelCard(name, "text", "chat", model=name, local=True,
                               endpoint="http://127.0.0.1:8765/v1", max_chars=30000)
                      for name in ["writer-a", "writer-b"]]
        self.bench = Benchmarks(self.store, self.cards)
        self.calls = []
        self.writer = patch.object(adapters, "execute", self.fake_writer)
        self.writer.start()
        self.addCleanup(self.writer.stop)

    def fake_writer(self, card, prompt, dependencies, directory, key=""):
        self.calls.append((card.id, prompt))
        directory.mkdir(parents=True, exist_ok=True)
        output = directory/"content.md"
        output.write_text("Synthetic creative output " + str(len(self.calls)))
        (directory/"usage.json").write_text('{"private": "operational receipt"}')
        return output

    def spec(self, fmt="article", target="draft"):
        return {"task": f"{fmt}:{target}", "baseline_model": "writer-a", "candidate_model": "writer-b",
                "cases": [{"id": f"case-{i}", "brief": {"topic": f"Original licensed fictional brief {i}",
                           "format": fmt, "profile": "private-profile", "local_only": True}} for i in range(6)]}

    def create(self, fmt="article", target="draft"):
        return self.bench.create("trial", self.spec(fmt, target))

    def finish(self, case):
        for arm in ["baseline", "candidate"]:
            result = self.bench.generate("trial", case["id"], arm)
            self.assertEqual(result["status"], "needs_review")

    def review(self, case):
        self.bench.review("trial", case["id"], {"A": 0.6, "B": 0.8}, "Synthetic test scores only.")

    def complete(self):
        trial = self.create()
        for partition in ["development", "holdout"]:
            for case in trial["cases"]:
                if case["partition"] == partition:
                    self.finish(case)
                    self.review(case)
            if partition == "development":
                self.bench.seal_development("trial")
        return trial

    def test_split_persisted_and_holdout_locked_in_all_execution_paths(self):
        trial = self.create()
        self.assertEqual(sum(c["partition"] == "development" for c in trial["cases"]), 3)
        self.assertEqual(trial["cases"], self.bench.inspect("trial")["cases"])
        case = next(c for c in trial["cases"] if c["partition"] == "holdout")
        with self.assertRaisesRegex(ValueError, "locked"):
            self.bench.generate("trial", case["id"], "baseline")
        with self.assertRaisesRegex(ValueError, "benchmark-generate"):
            self.bench.engine.execute(case["baseline_run"])
        with self.assertRaisesRegex(ValueError, "locked"):
            self.bench.engine.resume(case["baseline_run"])
        with self.assertRaises(ValueError):
            self.bench.packet("trial", case["id"])
        with self.assertRaises(ValueError):
            self.bench.seal_development("trial")
        self.assertEqual(self.calls, [])

    def test_shared_actual_prefix_target_models_and_no_duplicate_submission(self):
        trial = self.create("novel", "chapter")
        case = next(c for c in trial["cases"] if c["partition"] == "development")
        with self.assertRaisesRegex(ValueError, "baseline first"):
            self.bench.generate("trial", case["id"], "candidate")
        self.finish(case)
        self.assertEqual([c[0] for c in self.calls], ["writer-a", "writer-a", "writer-b"])
        self.assertEqual(self.calls[1][1], self.calls[2][1])
        base, candidate = [self.store.run(case[a+"_run"]) for a in ["baseline", "candidate"]]
        self.assertEqual(base["steps"][0]["result"]["sha256"], candidate["steps"][0]["result"]["sha256"])
        self.assertEqual(candidate["steps"][0]["result"]["reused_from"]["run"], base["id"])
        self.assertFalse(self.bench.generate("trial", case["id"], "candidate")["submitted"])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.store.metrics("private-profile")["steps"]), 3)
        with zipfile.ZipFile(self.bench.write_packet("trial", case["id"])["packet"]) as archive:
            self.assertIn("shared/outline.md", archive.namelist())
            self.assertEqual(archive.read("shared/outline.md"), self.bench.engine.artifact(base["id"], base["steps"][0]["result"]).read_bytes())

    def test_packet_contains_only_blind_creative_outputs_and_minimal_brief(self):
        case = next(c for c in self.create()["cases"] if c["partition"] == "development")
        self.finish(case)
        path = self.bench.write_packet("trial", case["id"])["packet"]
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {"A.md", "B.md", "review.json"})
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
            raw = b"".join(archive.read(n) for n in archive.namelist()).decode()
            for forbidden in ["writer-a", "writer-b", "private-profile", "8765", "usage", case["baseline_run"], case["candidate_run"]]:
                self.assertNotIn(forbidden, raw)
            self.assertEqual(set(json.loads(archive.read("review.json"))["brief"]), {"topic", "format", "language"})

    def test_reviews_immutable_and_development_cannot_enter_quality_feedback(self):
        trial = self.create()
        for case in trial["cases"]:
            if case["partition"] != "development":
                continue
            self.finish(case)
            self.review(case)
            with self.assertRaisesRegex(ValueError, "cannot be retuned"):
                self.review(case)
            self.bench.engine.approve(case["baseline_run"])
            with self.assertRaisesRegex(ValueError, "holdout calibration"):
                self.store.feedback(case["baseline_run"], "draft", 1)
        self.assertEqual(self.store.observations("private-profile", "text", "writer-a"), [])
        self.bench.seal_development("trial")
        dev = next(c for c in trial["cases"] if c["partition"] == "development")
        with self.assertRaisesRegex(ValueError, "sealed"):
            self.review(dev)
        with self.assertRaises(ValueError):
            self.bench.report("trial")

    def test_holdout_only_calibration_requires_approval_and_scopes_task_signature(self):
        trial = self.complete()
        report = self.bench.report("trial")
        self.assertEqual([report["partitions"][p]["n"] for p in ["development", "holdout"]], [3, 3])
        with self.assertRaisesRegex(ValueError, "Approve holdout"):
            self.bench.calibrate("trial")
        for case in trial["cases"]:
            if case["partition"] == "holdout":
                for arm in ["baseline", "candidate"]:
                    self.bench.engine.approve(case[arm+"_run"])
        self.assertEqual(self.bench.calibrate("trial")["holdout_feedback"], 6)
        self.bench.calibrate("trial")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 6)
        for card in self.cards:
            self.assertEqual(len(self.store.observations("private-profile", "text", card.id, "article:draft", card.signature())), 3)
            self.assertEqual(self.store.observations("private-profile", "text", card.id, "novel:chapter", card.signature()), [])
            changed = replace(card, model="replacement")
            self.assertEqual(self.store.observations("private-profile", "text", card.id, "article:draft", changed.signature()), [])

    def test_artifact_tampering_blocks_packet_review_report_and_calibration(self):
        trial = self.complete()
        case = next(c for c in trial["cases"] if c["partition"] == "holdout")
        run = self.store.run(case["baseline_run"])
        self.bench.engine.artifact(run["id"], run["steps"][0]["result"]).write_text("Changed")
        for operation in [lambda: self.bench.packet("trial", case["id"]), lambda: self.review(case),
                          lambda: self.bench.report("trial"), lambda: self.bench.calibrate("trial")]:
            with self.assertRaisesRegex(ValueError, "changed"):
                operation()

    def test_invalid_cases_and_unavailable_override_leave_no_runs(self):
        for change in ["duplicate", "extra", "unavailable", "too-few"]:
            spec = self.spec()
            if change == "duplicate":
                spec["cases"][1]["brief"]["topic"] = spec["cases"][0]["brief"]["topic"].upper()
            elif change == "extra":
                spec["cases"][0]["surprise"] = True
            elif change == "unavailable":
                spec["candidate_model"] = "missing"
            else:
                spec["cases"].pop()
            with self.assertRaises(ValueError):
                self.bench.create("invalid", spec)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            Engine(self.store, self.cards).plan(Brief("Fixture"), model_overrides={"draft": "missing"})

    def test_isolated_target_stops_before_missing_downstream_capabilities(self):
        trial = self.create("bookcast", "script")
        case = next(c for c in trial["cases"] if c["partition"] == "development")
        self.finish(case)
        for arm in ["baseline", "candidate"]:
            run = self.store.run(case[arm+"_run"])
            self.assertEqual([step["id"] for step in run["steps"]], ["script"])
            self.assertEqual(run["plan"]["isolated_task"], "bookcast:script")
        self.assertEqual(len(self.calls), 2)

    def test_imported_source_and_continuity_in_minimal_review_context(self):
        source = Path(self.temp.name)/"original.txt"
        source.write_text("An original fictional traveler returns to an empty observatory.")
        book = Library(self.store).import_book(source, "Fictional source", "owned", "Original fixture", 4000)
        spec = self.spec("novel", "chapter")
        for case in spec["cases"]:
            case.update({"book": book["id"], "continuity": "The traveler has a blue notebook."})
        trial = self.bench.create("trial", spec)
        case = next(c for c in trial["cases"] if c["partition"] == "development")
        self.finish(case)
        brief = self.bench.packet("trial", case["id"])["brief"]
        self.assertEqual(brief["source_text"], source.read_text())
        self.assertEqual(brief["continuity"], "The traveler has a blue notebook.")
        self.assertNotIn("book_id", brief)
        self.assertNotIn("rights_note", brief)

    def test_sign_test_direction_and_ties_are_explicit(self):
        trial = self.create()
        for partition in ["development", "holdout"]:
            for case in trial["cases"]:
                if case["partition"] != partition:
                    continue
                self.finish(case)
                internal = next(c for c in self.bench._load("trial")["cases"] if c["id"] == case["id"])
                # Known synthetic preferences test report arithmetic only.
                scores = {label: (0.9 if arm == "candidate" else 0.4)
                          for label, arm in zip(["A", "B"], json.loads(internal["display_order"]))}
                if partition == "development":
                    scores = {"A": 0.5, "B": 0.5}
                self.bench.review("trial", case["id"], scores, "Synthetic arithmetic fixture.")
            if partition == "development":
                self.bench.seal_development("trial")
        result = self.bench.report("trial")["partitions"]
        self.assertEqual(result["development"]["ties"], 3)
        self.assertEqual(result["development"]["one_sided_sign_test_p"], 1)
        self.assertEqual(result["holdout"]["wins"], 3)
        self.assertEqual(result["holdout"]["one_sided_sign_test_p"], 0.125)
        self.assertAlmostEqual(result["holdout"]["mean_delta"], 0.5)

    def test_cli_create_and_inspect(self):
        config = Path(self.temp.name)/"models.json"
        config.write_text(json.dumps({"models": [c.to_dict() for c in self.cards]}))
        spec = Path(self.temp.name)/"spec.json"
        spec.write_text(json.dumps(self.spec()))
        prefix = ["--data", str(self.store.root), "--config", str(config)]
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(prefix+["benchmark-new", "cli-trial", "--spec", str(spec)]), 0)
        self.assertEqual(json.loads(out.getvalue())["id"], "cli-trial")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(prefix+["benchmark-inspect", "cli-trial"]), 0)


if __name__ == "__main__":
    unittest.main()
