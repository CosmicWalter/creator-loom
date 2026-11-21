"""Synthetic text/review fixtures test integrity and reporting, not skill gains."""

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from contextlib import redirect_stdout
from creator_loom.cli import main
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.coaching import Coach
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.store import Store


class PracticeReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.card = ModelCard("writer", "text", "chat", model="fixture", local=True, endpoint="http://127.0.0.1:8765/v1", max_chars=30000)
        self.engine = Engine(self.store, [self.card])
        self.coach = Coach(self.store, self.engine)
        self.writer = patch.object(adapters, "execute", self.fake); self.writer.start(); self.addCleanup(self.writer.stop)
        self.run = self.engine.create(Brief("Original fictional lighthouse keeper sees a signal.", "novel", profile="practice-fixture"))
        self.engine.execute(self.run); self.engine.approve(self.run)
        self.path = self.store.root/"private-revision-name.txt"
        self.path.write_text("A blue light appears twice beyond the harbor. The keeper opens the shutter.")
        self.practice = self.coach.record(self.run, "chapter", self.path, "clarity", 0.1, 0.99, "Private self-assessment rationale is excluded from the blind packet.")["practice"]

    def fake(self, card, prompt, dependencies, directory, key=""):
        directory.mkdir(parents=True, exist_ok=True)
        output = directory/"content.md"
        output.write_text("Original outline: a blue signal, then a response." if directory.name == "outline" else "The keeper saw something and did something later.")
        (directory/"usage.json").write_text('{"private":"operational metadata"}')
        return output

    def scores(self, review_id, original=0.7, revised=0.4):
        review = self.coach.review_load(review_id)
        return {label: original if version == "original" else revised for label, version in zip(["A", "B"], review["display_order"])}

    def test_blind_packet_has_actual_pair_shared_context_and_no_self_ratings_or_mapping(self):
        review = self.coach.new_review(self.practice)
        self.assertEqual(self.coach.new_review(self.practice)["id"], review["id"])
        self.assertNotIn("display_order", review)
        with self.assertRaises(ValueError): self.coach.review_report(review["id"])
        with zipfile.ZipFile(io.BytesIO(self.coach.review_packet(review["id"]))) as archive:
            self.assertEqual(set(archive.namelist()), {"A.txt", "B.txt", "shared/input-1.txt", "review.json"})
            self.assertEqual(set(archive.read(label+".txt").decode() for label in ["A", "B"]), {self.path.read_text(), "The keeper saw something and did something later."})
            self.assertIn(b"Original outline", archive.read("shared/input-1.txt"))
            raw = b"".join(archive.read(name) for name in archive.namelist()).decode()
            for private in ["0.99", "self-assessment rationale", "private-revision-name", self.run, "practice-fixture", "writer", "8765", "operational metadata", "original_sha256"]:
                self.assertNotIn(private, raw)
            for entry in archive.infolist(): self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))

    def test_scores_are_immutable_can_disagree_with_self_assessment_and_never_calibrate_models(self):
        review = self.coach.new_review(self.practice)
        result = self.coach.score_review(review["id"], self.scores(review["id"]), "external-declared", "Synthetic reviewer prefers the original, independently of the saved self score.")
        self.assertAlmostEqual(result["revision_delta"], -0.3)
        self.assertEqual(result["reviewer_kind"], "external-declared")
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.coach.score_review(review["id"], {"A": 1, "B": 0}, "self", "Cannot retune after seeing the revision mapping.")
        progress = self.coach.progress("practice-fixture")
        self.assertAlmostEqual(progress["dimensions"][0]["mean_self_reported_delta"], 0.89)
        blind = progress["blind_revision_reviews"]["dimensions"][0]
        self.assertAlmostEqual(blind["mean_revision_delta"], -0.3)
        self.assertEqual(blind["comparisons"], 1)
        with self.store.connect() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)
        self.assertEqual(self.coach.blind_progress("other")["dimensions"], [])

    def test_revision_and_upstream_tampering_block_packet_scoring_and_aggregation(self):
        review = self.coach.new_review(self.practice)
        self.coach.score_review(review["id"], self.scores(review["id"]), "self", "Synthetic same-person review does not establish independence.")
        run = self.store.run(self.run)
        outline = self.engine.artifact(self.run, run["steps"][0]["result"])
        raw = outline.read_bytes(); outline.write_text("Changed upstream context")
        for call in [lambda: self.coach.review_packet(review["id"]), lambda: self.coach.review_report(review["id"]), lambda: self.coach.new_review(self.practice)]:
            with self.assertRaises(ValueError): call()
        self.assertEqual(self.coach.blind_progress("practice-fixture")["invalidated_comparisons"], 1)
        outline.write_bytes(raw)
        revised = self.engine.artifact(self.run, self.coach.practice(self.practice)["artifact"])
        revised.write_text("Changed stored revision")
        with self.assertRaises(ValueError): self.coach.review_packet(review["id"])
        self.assertEqual(self.coach.blind_progress("practice-fixture")["dimensions"], [])

    def test_invalid_text_and_score_declarations_leave_no_rating(self):
        self.path.write_bytes(b"\xff\x00")
        invalid = self.coach.record(self.run, "chapter", self.path, "clarity", 0.2, 0.5, "A non-text file cannot become a blind text packet.")
        with self.assertRaisesRegex(ValueError, "UTF-8"): self.coach.new_review(invalid["practice"])
        review = self.coach.new_review(self.practice)
        for scores, kind in [({"A": True, "B": 0.5}, "self"), ({"A": 0.5, "B": float('nan')}, "self"), ({"A": 0.5, "B": 0.6}, "verified-independent")]:
            with self.assertRaises(ValueError): self.coach.score_review(review["id"], scores, kind, "An invalid declaration must not be accepted.")
        self.assertFalse(self.coach.review_inspect(review["id"])["reviewed"])

    def test_required_public_credits_are_preserved_in_packet(self):
        run = self.store.run(self.run)
        run["plan"]["public_credits"] = [{"title": "Original fixture source", "attribution": "Original synthetic lyric credit.", "rights": "licensed"}]
        with self.store.connect() as db: db.execute("UPDATE runs SET plan=? WHERE id=?", (json.dumps(run["plan"]), self.run))
        review = self.coach.new_review(self.practice)
        with zipfile.ZipFile(io.BytesIO(self.coach.review_packet(review["id"]))) as archive:
            self.assertEqual(json.loads(archive.read("review.json"))["credits"][0]["attribution"], "Original synthetic lyric credit.")


    def test_cli_prepares_and_scores_the_saved_comparison_without_model_access(self):
        prefix = ["--data", str(self.store.root)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(prefix+["practice-blind", self.practice]), 0)
        review_id = json.loads(output.getvalue())["id"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(prefix+["practice-review-packet", review_id]), 0)
        self.assertTrue(Path(json.loads(output.getvalue())["file"]).is_file())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(prefix+["practice-review-score", review_id, "--a", "0.4", "--b", "0.6", "--reviewer-kind", "self", "--rationale", "Original fixture scores test CLI persistence only."]), 0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(prefix+["practice-review-report", review_id]), 0)
