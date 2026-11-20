"""Synthetic experiments verify decision mechanics, not model quality claims."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.cli import main
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.store import Store
from creator_loom.telemetry import estimate, provider_usage


class DecisionLearningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def card(self, name="a", **kwargs):
        return ModelCard(name, "text", "chat", model="test-model", local=True,
                         endpoint="http://127.0.0.1:8765/v1", max_chars=30000, **kwargs)

    def fake_writer(self, card, prompt, dependencies, directory, key=""):
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / "content.md"
        output.write_text("Explicit simulated inference for a decision-system test.")
        return output

    def measured(self, card, task, elapsed, outcome="done"):
        with self.store.connect() as db:
            self.store.measurement(db, "fixture-" + task.replace(":", "-"), card.id,
                                   "default", task, card, outcome, elapsed,
                                   {"status": "unknown", "token_cost_estimate": None})

    def test_outline_and_chapter_use_distinct_specialists(self):
        outline = self.card("outliner", quality=0.5,
                            task_quality={"novel:outline": 0.95, "novel:chapter": 0.2})
        prose = self.card("prose", quality=0.5,
                          task_quality={"novel:outline": 0.2, "novel:chapter": 0.95})
        plan = Engine(self.store, [outline, prose]).plan(Brief("A synthetic story", "novel"))
        self.assertEqual([s["model"]["id"] for s in plan["steps"]], ["outliner", "prose"])
        self.assertEqual(plan["steps"][1]["decision"]["candidates"][0]["task"], "novel:chapter")

    def test_article_feedback_does_not_contaminate_novel_or_another_profile(self):
        a, b = self.card("a", quality=0.8), self.card("b", quality=0.7)
        for i in range(3):
            engine = Engine(self.store, [a])
            run = engine.create(Brief(f"Article fixture {i}"))
            with patch.object(adapters, "execute", self.fake_writer):
                engine.execute(run)
            self.store.feedback(run, "draft", 0)
        engine = Engine(self.store, [a, b])
        self.assertEqual(engine.plan(Brief("Article"))["steps"][0]["model"]["id"], "b")
        self.assertEqual(engine.plan(Brief("Novel", "novel"))["steps"][0]["model"]["id"], "a")
        other = Brief("Article", profile="other")
        self.assertEqual(engine.plan(other)["steps"][0]["model"]["id"], "a")

    def test_backend_change_does_not_inherit_old_feedback_or_performance(self):
        a = self.card(quality=0.9)
        engine = Engine(self.store, [a])
        run = engine.create(Brief("A fixture"))
        with patch.object(adapters, "execute", self.fake_writer):
            engine.execute(run)
        self.store.feedback(run, "draft", 0)
        changed = replace(a, model="a-different-backend")
        decision = Engine(self.store, [changed]).plan(Brief("New backend"))["steps"][0]["decision"]
        self.assertEqual(decision["candidates"][0]["feedback_count"], 0)
        self.assertEqual(decision["candidates"][0]["observed_attempts"], 0)
        self.assertEqual(a.signature(), replace(a, quality=0.7, cost=0.2, latency=12).signature())
        self.assertNotEqual(a.signature(), replace(a, max_output_tokens=4096).signature())

    def test_slow_observed_model_is_filtered_by_latency_target(self):
        slow, fast = self.card("slow", quality=1), self.card("fast", quality=0.5)
        self.measured(slow, "article:draft", 300)
        plan = Engine(self.store, [slow, fast]).plan(Brief("Latency fixture", max_latency=20))
        self.assertEqual(plan["steps"][0]["model"]["id"], "fast")
        self.assertIn("observed latency", plan["steps"][0]["decision"]["rejected"][0]["reasons"][0])

    def test_joint_allocation_uses_observed_latency_totals(self):
        a = self.card("a", latency=5)
        self.measured(a, "novel:outline", 60)
        self.measured(a, "novel:chapter", 60)
        # Each inferred step is 16s; individually eligible, jointly infeasible.
        with self.assertRaisesRegex(ValueError, "No complete workflow"):
            Engine(self.store, [a]).plan(Brief("Latency fixture", "novel", max_latency=25))

    def test_joint_allocation_preserves_downstream_input_capacity(self):
        long_writer = self.card("long", quality=0.95, max_output_chars=20000)
        concise_writer = self.card("concise", quality=0.7, max_output_chars=1000)
        speech = ModelCard("speech", "audio", "speech", model="test-speech",
                           endpoint="http://127.0.0.1:8765/v1", local=True, max_chars=2000)
        plan = Engine(self.store, [long_writer, concise_writer, speech]).plan(Brief("A podcast", "podcast"))
        self.assertEqual(plan["steps"][0]["model"]["id"], "concise")
        self.assertEqual(plan["steps"][1]["reserved_input_chars"], 1000)
        self.assertEqual(plan["allocation"]["input_rejected_combinations"], 1)
        # Speech receives narration, not the long source topic/editor instructions.
        long_topic = Engine(self.store, [concise_writer, speech]).plan(Brief("topic " * 600, "podcast"))
        self.assertEqual(long_topic["steps"][1]["reserved_input_chars"], 1000)

    def test_provider_exceeding_output_bound_is_not_accepted(self):
        card = self.card(max_output_chars=5)
        engine = Engine(self.store, [card])
        run = engine.create(Brief("Bounded output"))
        response = json.dumps({"choices": [{"message": {"content": "Longer than five characters."}}]}).encode()
        with patch.object(adapters, "remote", return_value=response):
            with self.assertRaisesRegex(ValueError, "uncertain"):
                engine.execute(run)
        self.assertEqual(self.store.metrics("default")["steps"][0]["outcome"], "uncertain")

    def test_uncertain_attempt_penalizes_reliability_without_claiming_spend(self):
        a, b = self.card("a", quality=0.9), self.card("b", quality=0.85)
        self.measured(a, "article:draft", 120, "uncertain")
        plan = Engine(self.store, [a, b]).plan(Brief("Reliability fixture"))
        self.assertEqual(plan["steps"][0]["model"]["id"], "b")
        a_score = next(c for c in plan["steps"][0]["decision"]["candidates"] if c["model"] == "a")
        self.assertEqual(a_score["reliability"], 0.8)
        report = self.store.metrics("default")
        self.assertEqual(report["priced_steps"], 0)
        self.assertEqual(report["unpriced_steps"], 1)
        self.assertIsNone(report["steps"][0]["usage"]["token_cost_estimate"])

    def test_forget_removes_performance_influence(self):
        a = self.card()
        self.measured(a, "article:draft", 300)
        self.store.forget("default")
        self.assertEqual(self.store.performance("default", "article:draft", a.signature()), [])

    def test_pricing_uses_allowlisted_usage_and_frozen_card_rates(self):
        card = self.card(input_price_per_million=2, output_price_per_million=6)
        usage = provider_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                          "private_vendor_field": "must-not-persist"}})
        self.assertNotIn("private_vendor_field", usage)
        directory = self.store.root / "fixture"
        directory.mkdir()
        (directory / "provider-usage.json").write_text(json.dumps(usage))
        result = estimate(card, directory)
        self.assertAlmostEqual(result["token_cost_estimate"], 0.00005)
        self.assertEqual(result["rate_source"], "frozen_model_card")
        unpriced = estimate(replace(card, input_price_per_million=None, output_price_per_million=None), directory)
        self.assertIsNone(unpriced["token_cost_estimate"])

    def test_missing_or_invalid_usage_is_never_fabricated_as_zero(self):
        self.assertEqual(provider_usage({}), {"status": "not_reported"})
        for invalid in [True, -1, 1.5, "10", 1000000001]:
            self.assertEqual(provider_usage({"usage": {"prompt_tokens": invalid, "completion_tokens": 1}}),
                             {"status": "invalid"})
        self.assertEqual(estimate(self.card(), self.store.root)["token_cost_estimate"], None)

    def test_configuration_rejects_invalid_task_settings(self):
        for kwargs in [{"task_quality": {"invented-task": 0.8}}, {"task_quality": {"novel": float("nan")}},
                       {"max_output_tokens": True}, {"max_output_tokens": 0},
                       {"input_price_per_million": 2}, {"voice": "unsafe/voice"}]:
            with self.assertRaises(ValueError):
                self.card(**kwargs)

    def test_metrics_cli_reports_unknown_coverage(self):
        self.measured(self.card(), "article:draft", 1)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--data", str(self.store.root), "metrics"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["unpriced_steps"], 1)
        self.assertIn("not provider invoices", result["billing"])
