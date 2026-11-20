from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.domain import Brief, ModelCard
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
                else:
                    raw = json.dumps({"choices": [{"message": {"content": "An original ocean story."}}]}).encode()
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
                      local=True, api_key_env="LOOM_TEST_KEY", max_chars=30000),
            ModelCard("speaker", "audio", "speech", model="test-speaker", endpoint=self.endpoint,
                      local=True, api_key_env="LOOM_TEST_KEY", max_chars=30000)]

    def test_real_http_text_to_audio_contract(self):
        engine = Engine(self.store, self.cards())
        with patch.dict(os.environ, {"LOOM_TEST_KEY": "test-only-credential"}):
            run = engine.create(Brief("Ocean story", "podcast", local_only=True))
            engine.execute(run)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][0], "/v1/chat/completions")
        self.assertEqual(self.calls[1][1]["input"], "An original ocean story.")
        self.assertEqual(self.calls[1][2], "Bearer test-only-credential")
        self.assertNotIn("test-only-credential", (self.store.root / "loom.sqlite3").read_bytes().decode(errors="replace"))
        engine.approve(run)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is an optional system dependency")
    def test_actual_ffmpeg_bookcast_with_mock_inference(self):
        engine = Engine(self.store, self.cards())
        with patch.dict(os.environ, {"LOOM_TEST_KEY": "test-only-credential"}):
            run = engine.create(Brief("Ocean story", "bookcast", local_only=True))
            result = engine.execute(run)
        self.assertEqual(result["status"], "needs_review")
        film = engine.artifact(run, result["steps"][-1]["result"])
        self.assertIn(b"ftyp", film.read_bytes()[:64])
        self.assertEqual(len(self.calls), 2)
        engine.approve(run)


if __name__ == "__main__":
    unittest.main()
