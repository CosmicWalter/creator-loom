from __future__ import annotations

import io
import base64
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
import wave
import zlib
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.domain import Brief, ModelCard
from creator_loom.coaching import Coach
from creator_loom.engine import Engine
from creator_loom.learning import Learning
from creator_loom.routing import choose, load_cards
from creator_loom.store import Store


class SystemTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.engine = Engine(self.store, load_cards(None))

    def tearDown(self):
        self.temp.cleanup()

    def card(self, name="writer", quality=0.8, **kwargs):
        return ModelCard(name, "text", "chat", model="configured-model",
                         endpoint="http://127.0.0.1:8765/v1", quality=quality, **kwargs)

    def choose(self, cards, **kwargs):
        return choose(cards, self.store, profile="default", capability="text", language="zh",
                      chars=100, budget=1, local_only=False, max_latency=300, **kwargs)

    def fake_writer(self, card, prompt, dependencies, directory, key=""):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "content.md"
        path.write_text("A test creative artifact, not a real model inference.")
        return path

    def approved(self, topic, technique=None):
        engine = Engine(self.store, [self.card()])
        run = engine.create(Brief(topic), technique)
        with patch.object(adapters, "execute", self.fake_writer):
            engine.execute(run)
        engine.approve(run)
        return run

    def test_local_cover_creates_real_artifacts_and_review(self):
        run = self.engine.create(Brief("Ocean stories", "cover", local_only=True, budget=0))
        result = self.engine.execute(run)
        self.assertEqual(result["status"], "needs_review")
        artifact = self.engine.artifact(run, result["steps"][0]["result"])
        self.assertTrue(artifact.read_bytes().startswith(b"P6\n640 360\n255\n"))
        self.engine.approve(run)
        self.assertEqual(self.store.run(run)["status"], "approved")

    def test_changed_supplement_prevents_approval(self):
        run = self.engine.create(Brief("Ocean", "cover"))
        result = self.engine.execute(run)
        supplement = result["steps"][0]["result"]["supplements"][0]
        self.engine.artifact(run, supplement).write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.engine.approve(run)

    def test_no_replay_of_completed_run(self):
        run = self.engine.create(Brief("Ocean", "cover"))
        self.engine.execute(run)
        with self.assertRaisesRegex(ValueError, "cannot be replayed"):
            self.engine.execute(run)

    def test_concurrent_execution_is_claimed_once(self):
        run = self.engine.create(Brief("Ocean", "cover"))
        def execute():
            try:
                self.engine.execute(run)
                return "done"
            except ValueError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: execute(), range(2)))
        self.assertEqual(sorted(outcomes), ["done", "rejected"])

    def test_provider_uncertainty_is_persisted_without_replay(self):
        engine = Engine(self.store, [self.card()])
        run = engine.create(Brief("Ocean"))
        with patch.object(adapters, "execute", side_effect=adapters.ProviderUncertain("connection lost")) as call:
            with self.assertRaisesRegex(ValueError, "uncertain"):
                engine.execute(run)
            with self.assertRaises(ValueError):
                engine.execute(run)
            self.assertEqual(call.call_count, 1)
        result = self.store.run(run)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["steps"][0]["status"], "uncertain")

    def test_missing_credentials_rejected_before_execution(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "credential"):
                self.choose([self.card(api_key_env="LOOM_TEST_KEY")])

    def test_local_only_rejects_cloud_and_non_loopback_local_claim(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            ModelCard("false-local", "text", "chat", model="x", endpoint="https://example.com/v1", local=True)
        with self.assertRaisesRegex(ValueError, "off-device"):
            choose([self.card()], self.store, profile="default", capability="text", language="zh",
                   chars=1, budget=1, local_only=True, max_latency=300)

    def test_cost_language_and_input_constraints(self):
        cards = [self.card("expensive", cost=2), self.card("wrong-language", languages=("en",)),
                 self.card("short", max_chars=10), self.card("eligible")]
        decision = self.choose(cards)
        self.assertEqual(decision.selected, "eligible")
        self.assertEqual(len(decision.rejected), 3)

    def test_feedback_changes_future_routing_but_not_existing_plan(self):
        cards = [self.card("a", quality=0.8), self.card("b", quality=0.7)]
        engine = Engine(self.store, cards)
        frozen = engine.create(Brief("Frozen plan"))
        self.assertEqual(self.choose(cards).selected, "a")
        for i in range(4):
            run = Engine(self.store, [cards[0]]).create(Brief(f"Feedback topic {i}"))
            with patch.object(adapters, "execute", self.fake_writer):
                Engine(self.store, cards).execute(run)
            self.store.feedback(run, "draft", 0.0)
            self.store.feedback(run, "draft", 0.0)  # Updates; cannot stuff observations.
        self.assertEqual(len(self.store.observations("default", "text", "a")), 4)
        self.assertEqual(self.choose(cards).selected, "b")
        self.assertEqual(self.store.run(frozen)["plan"]["steps"][0]["model"]["id"], "a")
        self.assertEqual(self.store.observations("another-user", "text", "a"), [])

    def test_preferences_snapshot_and_forget_scope(self):
        self.store.set_preferences("default", {"tone": "warm"})
        run = self.engine.create(Brief("Ocean", "cover"))
        self.store.set_preferences("default", {"tone": "precise"})
        self.assertEqual(self.store.run(run)["plan"]["preferences"]["tone"], "warm")
        self.store.forget("default")
        self.assertEqual(self.store.preferences("default"), {})
        self.assertEqual(self.store.run(run)["status"], "ready")

    def test_joint_allocation_preserves_budget_for_later_steps(self):
        premium = self.card("premium", quality=1.0, cost=0.8)
        economical = self.card("economical", quality=0.7, cost=0.2)
        speech = ModelCard("speaker", "audio", "speech", model="speech",
                           endpoint="http://127.0.0.1:8765/v1", cost=0.5, max_chars=30000)
        plan = Engine(self.store, [premium, economical, speech]).plan(Brief("A story", "podcast", budget=1))
        self.assertEqual(plan["steps"][0]["model"]["id"], "economical")
        self.assertAlmostEqual(plan["estimated_cost"], 0.7)
        self.assertEqual(plan["allocation"]["combinations"], 2)
        self.assertEqual(plan["allocation"]["feasible"], 1)

    def test_joint_allocation_rejects_infeasible_total_latency(self):
        writer = self.card(latency=200)
        speech = ModelCard("speaker", "audio", "speech", model="speech",
                           endpoint="http://127.0.0.1:8765/v1", latency=200, max_chars=30000)
        with self.assertRaisesRegex(ValueError, "No complete workflow"):
            Engine(self.store, [writer, speech]).plan(Brief("A story", "podcast", max_latency=300))

    def test_artifact_cannot_escape_run_directory(self):
        with self.assertRaises(ValueError):
            self.engine.artifact("run", {"file": "../../loom.sqlite3", "sha256": "fake"})

    def test_new_technique_needs_paired_evaluation(self):
        learning = Learning(self.store, self.engine)
        learning.propose("specificity", "https://example.com/research", "Use concrete sensory details.")
        with self.assertRaisesRegex(ValueError, "evaluated"):
            learning.promote("specificity")
        with self.assertRaisesRegex(ValueError, "three"):
            learning.evaluate("specificity", [])
        pairs = []
        for i in range(3):
            topic = f"Evaluation topic {i}"
            pairs.append({"baseline": self.approved(topic), "candidate": self.approved(topic, "specificity"),
                          "baseline_score": 0.6, "candidate_score": 0.8,
                          "rationale": "Test-only human score fixture, not a benchmark result."})
        result = learning.evaluate("specificity", pairs)
        self.assertTrue(result["passed"])
        learning.promote("specificity")
        plan = self.engine.plan(Brief("Future cover", "cover"))
        self.assertEqual(plan["technique"], "specificity")
        learning.rollback("specificity")
        self.assertIsNone(self.engine.plan(Brief("Future cover", "cover"))["technique"])

    def test_evaluation_cannot_reuse_topics_or_unrelated_candidate(self):
        learning = Learning(self.store, self.engine)
        learning.propose("specificity", "https://example.com/research", "Use concrete details.")
        a, b = self.approved("Same topic"), self.approved("Same topic", "specificity")
        pair = {"baseline": a, "candidate": b, "baseline_score": 0.5, "candidate_score": 0.9,
                "rationale": "A test rationale for repeated evidence."}
        with self.assertRaisesRegex(ValueError, "distinct"):
            learning.evaluate("specificity", [pair] * 3)

    def test_evaluation_rejects_model_and_preference_confounds(self):
        learning = Learning(self.store, self.engine)
        learning.propose("specificity", "https://example.com/research", "Use concrete details.")
        baseline = self.approved("Same topic")
        self.store.set_preferences("default", {"tone": "changed during experiment"})
        candidate = self.approved("Same topic", "specificity")
        pair = {"baseline": baseline, "candidate": candidate, "baseline_score": 0.5,
                "candidate_score": 0.9, "rationale": "This experiment changed more than its technique."}
        with self.assertRaisesRegex(ValueError, "freeze model and preference"):
            learning.evaluate("specificity", [pair] * 3)
        self.store.forget("default")
        altered = Engine(self.store, [self.card(name="another-model")])
        candidate = altered.create(Brief("Same topic"), "specificity")
        with patch.object(adapters, "execute", self.fake_writer):
            altered.execute(candidate)
        altered.approve(candidate)
        pair["candidate"] = candidate
        with self.assertRaisesRegex(ValueError, "freeze model and preference"):
            learning.evaluate("specificity", [pair] * 3)

    def test_promotion_rechecks_evaluated_artifact_hashes(self):
        learning = Learning(self.store, self.engine)
        learning.propose("specificity", "https://example.com/research", "Use concrete details.")
        pairs = []
        for i in range(3):
            pairs.append({"baseline": self.approved(f"Topic {i}"),
                          "candidate": self.approved(f"Topic {i}", "specificity"),
                          "baseline_score": 0.5, "candidate_score": 0.7,
                          "rationale": "Synthetic test score fixture for artifact binding."})
        learning.evaluate("specificity", pairs)
        run = self.store.run(pairs[0]["candidate"])
        self.engine.artifact(run["id"], run["steps"][0]["result"]).write_text("Replaced after evaluation")
        with self.assertRaisesRegex(ValueError, "changed"):
            learning.promote("specificity")

    def test_coaching_records_actual_changed_revision_and_profile_progress(self):
        run = self.approved("Original story")
        coach = Coach(self.store, self.engine)
        workbook = coach.workbook(run)
        self.assertIn("clarity", workbook["stages"][0]["rubric"])
        revision = self.root / "edited.md"
        revision.write_text("A deliberately revised test story with one concrete example.")
        result = coach.record(run, "draft", revision, "clarity", 0.4, 0.7,
                              "Added a concrete example to explain the opening idea.")
        self.assertAlmostEqual(result["delta"], 0.3)
        self.engine.artifact(run, result["artifact"])
        self.assertEqual(coach.progress("default")["dimensions"][0]["attempts"], 1)
        self.assertEqual(coach.progress("another-user")["dimensions"], [])

    def test_practice_rejects_unchanged_artifact_and_wrong_rubric(self):
        run = self.approved("Original story")
        coach = Coach(self.store, self.engine)
        state = self.store.run(run)
        original = self.engine.artifact(run, state["steps"][0]["result"])
        with self.assertRaisesRegex(ValueError, "changed artifact"):
            coach.record(run, "draft", original, "clarity", 0.1, 0.9, "No actual change was made.")
        with self.assertRaisesRegex(ValueError, "rubric"):
            coach.record(run, "draft", original, "pacing", 0.1, 0.9, "Incorrect rubric for this medium.")

    def test_invalid_model_values_and_endpoint_secrets_rejected(self):
        for value in [float("nan"), float("inf"), -0.1, True]:
            with self.assertRaises(ValueError):
                self.card(quality=value)
        userinfo_endpoint = "https://" + "user:password" + "@" + "example.com/v1"
        for endpoint in ["http://example.com/v1", userinfo_endpoint,
                         "https://example.com/v1?key=private"]:
            with self.assertRaises(ValueError):
                ModelCard("bad", "text", "chat", model="x", endpoint=endpoint)


class ProviderContractTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, body, self.headers.get("Authorization")))
                if self.path.endswith("/audio/speech"):
                    data = io.BytesIO()
                    with wave.open(data, "wb") as audio:
                        audio.setnchannels(1)
                        audio.setsampwidth(2)
                        audio.setframerate(8000)
                        audio.writeframes(b"\0\0" * 4000)
                    raw = data.getvalue()
                elif self.path.endswith("/images/generations"):
                    def chunk(kind, data):
                        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind+data))
                    png = b"\x89PNG\r\n\x1a\n"
                    png += chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 2, 0, 0, 0))
                    png += chunk(b"IDAT", zlib.compress(b"\0\x50\x90\xb0")) + chunk(b"IEND", b"")
                    raw = json.dumps({"data": [{"b64_json": base64.b64encode(png).decode()}]}).encode()
                else:
                    raw = json.dumps({"choices": [{"message": {"content": "An original ocean story."}}],
                                      "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                                "private_field": "must-not-persist"}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def cards(self):
        return load_cards(None) + [
            ModelCard("writer", "text", "chat", model="test-writer", endpoint=self.endpoint,
                      local=True, api_key_env="LOOM_TEST_KEY", max_chars=30000, max_output_tokens=1234,
                      input_price_per_million=2, output_price_per_million=6),
            ModelCard("speaker", "audio", "speech", model="test-speaker", endpoint=self.endpoint,
                      local=True, api_key_env="LOOM_TEST_KEY", max_chars=30000, voice="narrator")]

    def test_real_http_text_to_audio_contract(self):
        engine = Engine(self.store, self.cards())
        with patch.dict(os.environ, {"LOOM_TEST_KEY": "test-only-credential"}):
            run = engine.create(Brief("Ocean story", "podcast", local_only=True))
            engine.execute(run)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][0], "/v1/chat/completions")
        self.assertEqual(self.calls[1][1]["input"], "An original ocean story.")
        self.assertEqual(self.calls[1][2], "Bearer test-only-credential")
        self.assertEqual(self.calls[0][1]["max_tokens"], 1234)
        self.assertEqual(self.calls[1][1]["voice"], "narrator")
        report = self.store.metrics("default", run)
        self.assertEqual(report["priced_steps"], 1)
        self.assertEqual(report["unpriced_steps"], 1)
        self.assertAlmostEqual(report["known_token_cost_estimate"], 0.00005)
        self.assertGreater(report["steps"][0]["elapsed_seconds"], 0)
        self.assertNotIn("must-not-persist", (self.store.root / "loom.sqlite3").read_bytes().decode(errors="replace"))
        self.assertNotIn("test-only-credential", (self.store.root / "loom.sqlite3").read_bytes().decode(errors="replace"))
        engine.approve(run)

    def test_real_http_image_contract(self):
        image = ModelCard("image", "image", "image", model="test-image", endpoint=self.endpoint,
                          local=True, quality=0.9)
        engine = Engine(self.store, [image])
        run = engine.create(Brief("Ocean cover", "cover", local_only=True))
        result = engine.execute(run)
        output = engine.artifact(run, result["steps"][0]["result"])
        self.assertEqual(output.suffix, ".png")
        self.assertEqual(self.calls[0][0], "/v1/images/generations")
        self.assertEqual(self.calls[0][1]["response_format"], "b64_json")
        engine.approve(run)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe are optional system dependencies")
    def test_actual_ffmpeg_bookcast_with_mock_inference(self):
        engine = Engine(self.store, self.cards())
        with patch.dict(os.environ, {"LOOM_TEST_KEY": "test-only-credential"}):
            run = engine.create(Brief("Ocean story", "bookcast", local_only=True))
            result = engine.execute(run)
        self.assertEqual(result["status"], "needs_review")
        film = engine.artifact(run, result["steps"][-1]["result"])
        self.assertIn(b"ftyp", film.read_bytes()[:64])
        inspection = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(film)]))
        self.assertEqual({s["codec_type"] for s in inspection["streams"]}, {"video", "audio"})
        self.assertAlmostEqual(float(inspection["format"]["duration"]), 0.5, delta=0.15)
        video = next(s for s in inspection["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (1280, 720))
        self.assertEqual(len(self.calls), 2)
        engine.approve(run)


if __name__ == "__main__":
    unittest.main()
