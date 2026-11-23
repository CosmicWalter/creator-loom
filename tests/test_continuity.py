"""Original fiction and simulated candidate JSON test reviewed continuity changes."""

import copy
import json
import io
from contextlib import redirect_stdout
from creator_loom.cli import main
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.continuity import Continuity
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.library import Library
from creator_loom.series import Series
from creator_loom.story_memory import StoryMemory
from creator_loom.store import Store


class ContinuityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        source = Path(self.temp.name)/"fiction.txt"
        source.write_text("Chapter 1\nRowan carries a blue notebook.\n\nChapter 2\nRowan observes the distant island.")
        self.book = Library(self.store).import_book(source, "Original fiction", "owned")
        self.cards = [ModelCard("writer", "text", "chat", model="fixture", endpoint="http://127.0.0.1:8765/v1", local=True, max_chars=40000)]
        self.engine = Engine(self.store, self.cards); self.series = Series(self.store, self.engine); self.memory = StoryMemory(self.store); self.service = Continuity(self.store, self.cards)
        self.story = self.series.create(self.book["id"], Brief("Adapt original fiction", "novel", local_only=True))["id"]
        seed = {"characters": [{"id": "rowan", "name": "Rowan", "facts": [{"id": "notebook", "kind": "appearance", "text": "Rowan has a blue notebook.", "citation": {"kind": "source", "unit": 0, "quote": "Rowan carries a blue notebook."}}]}]}
        self.memory.update(self.story, seed, 1, 0, "Reviewed original character reference and exact source quotation.", True)
        self.value = self.output(); self.calls = []
        patcher = patch.object(adapters, "execute", self.fake); patcher.start(); self.addCleanup(patcher.stop)
        self.episode = self.series.next(self.story); self.engine.execute(self.episode); self.engine.approve(self.episode)
        self.series.accept(self.story, self.episode, "Rowan opened the shutter.", 2)

    def output(self):
        return {"status": "suggestions", "summary": "One existing character has a newly observed state.", "changes": [
            {"character": "rowan", "name": "Rowan", "fact": None, "kind": "state", "text": "Rowan has opened a green shutter.", "quote": "Rowan opens a green shutter", "reason": "The accepted passage states this action, but its persistence still needs human review."},
            {"character": None, "name": "Mira", "fact": None, "kind": "relationship", "text": "Mira is Rowan's friend.", "quote": "Mira greets her friend Rowan", "reason": "The accepted text suggests a friendship; check character attribution and scope."}
        ], "warnings": ["No automatic semantic contradiction or temporal-lifetime verification was performed."]}

    def fake(self, card, prompt, dependencies, directory, key=""):
        self.calls.append(prompt); directory.mkdir(parents=True, exist_ok=True)
        output = directory/"content.md"
        output.write_text(json.dumps(self.value) if "Format: continuity;" in prompt else "Rowan opens a green shutter. Mira greets her friend Rowan.")
        return output

    def create(self, name="suggestion"):
        return self.service.create(name, self.story, {"budget": 1, "local_only": True, "max_latency": 300}, request_key=name+"-request")

    def completed(self):
        proposal = self.create(); self.engine.execute(proposal["run_id"]); self.engine.approve(proposal["run_id"]); return proposal

    def test_freezes_accepted_episode_and_memory_without_private_metadata_in_prompt(self):
        proposal = self.create(); self.assertEqual(self.create()["run_id"], proposal["run_id"])
        plan = self.store.run(proposal["run_id"])["plan"]
        self.assertEqual(plan["story_context"]["episode"], self.episode)
        self.assertEqual(plan["story_context"]["memory"]["version"], 1)
        prompt = plan["steps"][0]["prompt"]
        self.assertIn("Rowan has a blue notebook.", prompt); self.assertIn("Rowan opens a green shutter", prompt)
        self.assertNotIn(self.episode, prompt); self.assertNotIn(self.story, prompt)
        self.assertNotIn("Reviewed original character reference", prompt)
        self.assertEqual(self.memory.snapshot(self.story)["version"], 1)
        self.assertEqual(len(self.calls), 2)  # reserving the suggestion never infers

    def test_explicit_subset_acceptance_preserves_old_facts_and_reuses_decision(self):
        proposal = self.completed()
        self.assertEqual(len(self.service.draft(proposal["id"])["changes"]), 2)
        accepted = self.service.accept(proposal["id"], [0], "Reviewed quote, character identity and temporal scope of the selected change.", True)
        self.assertEqual(accepted["result_version"], 2)
        payload = self.memory.snapshot(self.story)["payload"]
        self.assertEqual(len(payload["characters"]), 1)
        self.assertEqual(len(payload["characters"][0]["facts"]), 2)
        self.assertEqual(payload["characters"][0]["facts"][0]["id"], "notebook")
        self.service.accept(proposal["id"], [0], "Reviewed quote, character identity and temporal scope of the selected change.", True)
        with self.assertRaises(ValueError): self.service.accept(proposal["id"], [1], "Cannot change a frozen acceptance decision.", True)
        next_run = self.series.next(self.story)
        self.assertIn("Rowan has opened a green shutter.", self.store.run(next_run)["plan"]["steps"][1]["prompt"])
        self.engine.verify_artifacts(self.store.run(self.episode))

    def test_approval_and_human_review_are_both_required(self):
        proposal = self.create(); self.engine.execute(proposal["run_id"])
        with self.assertRaisesRegex(ValueError, "Approve"): self.service.accept(proposal["id"], [0], "Reviewed fixture candidates carefully.", True)
        self.engine.approve(proposal["run_id"])
        with self.assertRaises(ValueError): self.service.accept(proposal["id"], [0], "Review cannot be assumed from model output.", False)
        with self.assertRaises(ValueError): self.service.accept(proposal["id"], [True], "Boolean indexes must not be accepted.", True)
        self.assertEqual(self.memory.snapshot(self.story)["version"], 1)

    def test_invalid_quotes_renames_unknown_replacements_and_duplicate_edits_are_blocked(self):
        for index, mode in enumerate(["quote", "identity", "fact", "duplicate", "code"]):
            self.value = copy.deepcopy(self.output())
            change = self.value["changes"][0]
            if mode == "quote": change["quote"] = "An invented quotation absent from the accepted episode."
            if mode == "identity": change["name"] = "A different existing identity"
            if mode == "fact": change["fact"] = "missing-fact"
            if mode == "duplicate": self.value["changes"].append(copy.deepcopy(change))
            if mode == "code": self.value["commands"] = ["untrusted-model-command"]
            proposal = self.create("invalid-"+str(index)); self.engine.execute(proposal["run_id"])
            with self.assertRaises(ValueError): self.service.draft(proposal["id"])
        self.assertEqual(self.memory.snapshot(self.story)["version"], 1)

    def test_new_memory_or_pending_episode_makes_acceptance_stale(self):
        proposal = self.completed()
        self.series.next(self.story)
        self.assertTrue(self.service.inspect(proposal["id"])["stale"])
        with self.assertRaisesRegex(ValueError, "Series or memory changed"): self.service.accept(proposal["id"], [0], "A newer pending input must not be overwritten.", True)
        with self.assertRaises(ValueError): self.create("another")

    def test_accepted_story_or_suggestion_tampering_blocks_followup(self):
        proposal = self.completed()
        run = self.store.run(proposal["run_id"]); output = self.engine.artifact(run["id"], run["steps"][0]["result"])
        raw = output.read_bytes(); output.write_text("Changed suggestion")
        with self.assertRaises(ValueError): self.service.accept(proposal["id"], [0], "Changed suggestion cannot become a memory update.", True)
        output.write_bytes(raw)
        episode = self.store.run(self.episode); source = self.engine.artifact(self.episode, episode["steps"][-1]["result"]); source.write_text("Changed accepted fiction")
        with self.assertRaises(ValueError): self.service.draft(proposal["id"])
        self.assertEqual(self.memory.snapshot(self.story)["version"], 1)

    def test_no_change_is_valid_and_cannot_create_an_empty_revision(self):
        self.value["changes"] = []
        proposal = self.completed()
        self.assertEqual(self.service.draft(proposal["id"])["changes"], [])
        with self.assertRaises(ValueError): self.service.accept(proposal["id"], [], "No candidate means no automatic memory update.", True)

    def test_replacement_is_explicit_and_old_memory_version_remains(self):
        self.value["changes"][0].update(fact="notebook", kind="state", text="The current accepted passage records Rowan opening the shutter.")
        proposal = self.completed(); self.service.accept(proposal["id"], [0], "Explicitly reviewed the old fact being replaced and the evidence scope.", True)
        before = self.memory.snapshot(self.story, 1)["payload"]["characters"][0]["facts"][0]
        after = self.memory.snapshot(self.story)["payload"]["characters"][0]["facts"][0]
        self.assertEqual(before["text"], "Rowan has a blue notebook.")
        self.assertEqual(after["id"], "notebook"); self.assertNotEqual(before["text"], after["text"])


    def test_failed_commit_does_not_partially_update_memory(self):
        proposal = self.completed()
        original = self.service.memory.update_in
        def fail_after_memory_write(*args):
            original(*args)
            raise OSError("Synthetic failure between atomic local writes")
        with patch.object(self.service.memory, "update_in", fail_after_memory_write):
            with self.assertRaises(OSError): self.service.accept(proposal["id"], [0], "Reviewed candidate before synthetic persistence failure.", True)
        self.assertEqual(self.memory.snapshot(self.story)["version"], 1)
        self.assertEqual(self.service.inspect(proposal["id"])["state"], "planned")
        self.assertEqual(self.service.accept(proposal["id"], [0], "Reviewed candidate after safe local rollback.", True)["result_version"], 2)

    def test_cli_inspects_and_selects_existing_model_output(self):
        proposal = self.completed()
        prefix = ["--data", str(self.store.root)]
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(main(prefix+["continuity-draft", proposal["id"]]), 0)
        self.assertEqual(len(json.loads(output.getvalue())["changes"]), 2)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(prefix+["continuity-accept", proposal["id"], "--selected", "0", "--reviewed", "--note", "Reviewed quoted state change and kept the remaining facts."]), 0)
        self.assertEqual(self.memory.snapshot(self.story)["version"], 2)
