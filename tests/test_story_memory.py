"""Original fiction and simulated generation test reviewed memory provenance."""

import copy
import json
import sqlite3
from contextlib import closing, redirect_stdout
import io
from creator_loom.cli import main
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.library import Library
from creator_loom.series import Series
from creator_loom.story_memory import StoryMemory
from creator_loom.store import Store


class StoryMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"data")
        source = Path(self.temp.name)/"original.txt"
        source.write_text("Chapter 1\nRowan is the keeper of a lighthouse. Rowan carries a blue notebook.\n\nChapter 2\nRowan answers a distant signal using a mirror.")
        self.library = Library(self.store)
        self.book = self.library.import_book(source, "Original fiction fixture", "owned")
        self.cards = [ModelCard("writer", "text", "chat", model="fixture", endpoint="http://127.0.0.1:8765/v1", local=True, max_chars=30000)]
        self.engine = Engine(self.store, self.cards); self.series = Series(self.store, self.engine)
        self.created = self.series.create(self.book["id"], Brief("Adapt the original fiction", "novel", local_only=True))
        self.name = self.created["id"]; self.memory = StoryMemory(self.store)
        self.prompts = []
        patcher = patch.object(adapters, "execute", self.fake); patcher.start(); self.addCleanup(patcher.stop)

    def fake(self, card, prompt, dependencies, directory, key=""):
        self.prompts.append(prompt); directory.mkdir(parents=True, exist_ok=True)
        output = directory/"content.md"; output.write_text("Rowan opens a green shutter to answer the distant signal."); return output

    def payload(self):
        return {"characters": [{"id": "rowan", "name": "Rowan", "facts": [{"id": "role", "kind": "identity", "text": "Rowan is the lighthouse keeper.", "citation": {"kind": "source", "unit": 0, "quote": "Rowan is the keeper of a lighthouse."}}]}]}

    def update(self, payload=None, reviewed=True):
        state = self.memory.inspect(self.name)
        return self.memory.update(self.name, payload or self.payload(), state["series_version"], state["current_version"], "Reviewed every stated fact, citation and scope against the actual fiction.", reviewed)

    def episode(self):
        run = self.series.next(self.name); self.engine.execute(run); self.engine.approve(run)
        state = self.series.inspect(self.name)
        self.series.accept(self.name, run, "The shutter has been opened.", state["version"])
        return run

    def test_reviewed_facts_enter_prompts_without_evidence_ids_or_review_notes(self):
        state = self.update()
        self.assertEqual((state["current_version"], state["series_version"]), (1, 2))
        run = self.series.next(self.name); plan = self.store.run(run)["plan"]
        self.assertEqual(plan["context"]["character_memory"]["version"], 1)
        self.assertEqual(plan["context"]["character_memory"]["payload"]["characters"][0]["name"], "Rowan")
        for step in plan["steps"]:
            self.assertIn("Human-reviewed character facts", step["prompt"])
            self.assertIn("Rowan is the lighthouse keeper.", step["prompt"])
            self.assertNotIn("Reviewed every stated fact", step["prompt"])
            self.assertNotIn(self.name, step["prompt"])
        self.engine.execute(run)
        self.assertEqual(len(self.prompts), 2)

    def test_pending_episode_and_stale_versions_block_memory_edits(self):
        self.update()
        with self.assertRaises(ValueError):
            self.memory.update(self.name, {"characters": []}, 1, 0, "Cannot overwrite stale reviewed state.", True)
        self.series.next(self.name)
        with self.assertRaisesRegex(ValueError, "pending"):
            self.update({"characters": []})

    def test_exact_citations_bound_sources_and_future_units_are_rejected(self):
        for change in ["unreviewed", "quote", "future", "hash", "duplicate"]:
            value = self.payload()
            fact = value["characters"][0]["facts"][0]
            if change == "quote": fact["citation"]["quote"] = "A fabricated source statement is not present."
            if change == "future": fact["citation"] = {"kind": "source", "unit": 1, "quote": "Rowan answers a distant signal using a mirror."}
            if change == "hash": fact["citation"]["sha256"] = "changed"
            if change == "duplicate": value["characters"].append(copy.deepcopy(value["characters"][0]))
            with self.assertRaises(ValueError): self.update(value, reviewed=change != "unreviewed")
        self.assertEqual(self.memory.inspect(self.name)["current_version"], 0)

    def test_accepted_episode_citations_and_old_versions_remain_inspectable(self):
        self.update(); run = self.episode()
        value = self.payload()
        value["characters"][0]["facts"].append({"id": "shutter", "kind": "state", "text": "Rowan has opened the green shutter.", "citation": {"kind": "episode", "run": run, "step": "chapter", "quote": "Rowan opens a green shutter"}})
        state = self.update(value)
        self.assertEqual(state["current_version"], 2)
        self.assertEqual(len(self.memory.inspect(self.name, 1)["snapshot"]["payload"]["characters"][0]["facts"]), 1)
        self.engine.verify_artifacts(self.store.run(run))
        next_run = self.series.next(self.name)
        self.assertIn("Rowan has opened the green shutter.", self.store.run(next_run)["plan"]["steps"][1]["prompt"])
        self.assertEqual(len(self.memory.evidence_options(self.name)), 4)  # two source units + outline/chapter

    def test_unaccepted_episode_and_other_series_cannot_supply_facts(self):
        run = self.series.next(self.name); self.engine.execute(run); self.engine.approve(run)
        state = self.series.inspect(self.name)
        self.series.reject(self.name, run, state["version"], "Not accepted into this story's continuity.")
        value = self.payload(); value["characters"][0]["facts"][0]["citation"] = {"kind": "episode", "run": run, "step": "chapter", "quote": "Rowan opens a green shutter"}
        with self.assertRaisesRegex(ValueError, "accepted episode"): self.update(value)

    def test_memory_record_and_cited_episode_tampering_block_execution(self):
        self.update(); first = self.episode()
        value = self.payload(); value["characters"][0]["facts"][0]["citation"] = {"kind": "episode", "run": first, "step": "chapter", "quote": "Rowan opens a green shutter"}
        self.update(value)
        next_run = self.series.next(self.name)
        first_run = self.store.run(first); path = self.engine.artifact(first, first_run["steps"][1]["result"])
        raw = path.read_bytes(); path.write_text("Changed cited evidence")
        with self.assertRaises(ValueError): self.engine.execute(next_run)
        self.assertEqual(self.store.run(next_run)["status"], "ready")
        path.write_bytes(raw)
        with self.store.connect() as db: db.execute("UPDATE story_memories SET sha256='changed' WHERE series_id=? AND version=2", (self.name,))
        with self.assertRaises(ValueError): self.engine.execute(next_run)
        self.assertEqual(len(self.prompts), 2)  # only the first accepted episode ran

    def test_evidence_text_is_available_only_for_current_or_accepted_history(self):
        self.assertIn("blue notebook", self.memory.evidence_text(self.name, {"kind": "source", "unit": 0}))
        with self.assertRaises(ValueError): self.memory.evidence_text(self.name, {"kind": "source", "unit": 1})
        snapshot = self.memory.snapshot(self.name)
        wrong = copy.deepcopy(snapshot); wrong["payload"] = {"characters": [{"invented": "fact"}]}
        with self.assertRaises(ValueError): self.memory.validate(wrong)


    def test_other_series_accepted_chapter_is_not_an_authorized_fact_source(self):
        other = self.series.create(self.book["id"], Brief("Another original adaptation", "novel", local_only=True))
        run = self.series.next(other["id"]); self.engine.execute(run); self.engine.approve(run)
        self.series.accept(other["id"], run, "Other series history.", 1)
        payload = self.payload(); payload["characters"][0]["facts"][0]["citation"] = {"kind": "episode", "run": run, "step": "chapter", "quote": "Rowan opens a green shutter"}
        with self.assertRaisesRegex(ValueError, "accepted episode"): self.update(payload)

    def test_legacy_series_migration_and_cli_review(self):
        legacy = Path(self.temp.name)/"legacy"; legacy.mkdir()
        with closing(sqlite3.connect(legacy/"loom.sqlite3")) as db, db:
            db.execute("CREATE TABLE series(id TEXT PRIMARY KEY,definition TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 1,continuity TEXT NOT NULL DEFAULT '',pending_run TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO series(id,definition) VALUES('legacy','{}')")
        migrated = Store(legacy)
        with migrated.connect() as db: self.assertEqual(db.execute("SELECT memory_version FROM series WHERE id='legacy'").fetchone()[0], 0)
        spec = Path(self.temp.name)/"facts.json"; spec.write_text(json.dumps(self.payload()))
        prefix = ["--data", str(self.store.root)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(prefix+["series-memory-update", self.name, "--spec", str(spec), "--base-version", "1", "--memory-version", "0", "--reviewed", "--note", "Original source and each character fact reviewed."]), 0)
        output = io.StringIO()
        with redirect_stdout(output): self.assertEqual(main(prefix+["series-memory", self.name, "--version", "1"]), 0)
        self.assertEqual(json.loads(output.getvalue())["snapshot"]["version"], 1)
