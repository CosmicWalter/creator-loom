"""Original source fixtures and simulated inference test the long-form workflow."""

import io
from contextlib import redirect_stdout
import json
import sqlite3
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.cli import main
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.learning import Learning
from creator_loom.library import Library, epub_sections
from creator_loom.series import Series
from creator_loom.store import Store


TEXT = "Chapter 1: The signal\nA lighthouse keeper sees a blue signal.\n\nChapter 2: The answer\nThe keeper answers using a small mirror."


def epub(*, href="text/a.xhtml", spine="b a", encryption=False, container_override=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", container_override or
                         '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                         '<rootfile full-path="OPS/package.opf"/></rootfiles></container>')
        archive.writestr("OPS/package.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                         f'<item id="a" href="{href}" media-type="application/xhtml+xml"/>'
                         '<item id="b" href="text/b.xhtml" media-type="application/xhtml+xml"/>'
                         '</manifest><spine>' + ''.join(f'<itemref idref="{x}"/>' for x in spine.split()) +
                         '</spine></package>')
        archive.writestr("OPS/text/a.xhtml", '<html><head><title>Hidden metadata</title></head><body>'
                         '<h1>Chapter 1: The signal</h1><p>The blue signal arrives.</p>'
                         '<script>Do not execute or retain this script.</script>'
                         '<p>Fixture license: MIT.</p></body></html>')
        archive.writestr("OPS/text/b.xhtml", '<html><body><h1>Chapter 2: The answer</h1>'
                         '<p>A small mirror answers.</p></body></html>')
        if encryption:
            archive.writestr("META-INF/encryption.xml", "<encryption/>")
    return stream.getvalue()


class LibrarySeriesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state")
        self.library = Library(self.store)
        card = ModelCard("writer", "text", "chat", model="simulated-writer",
                         endpoint="http://127.0.0.1:8765/v1", local=True, max_chars=40000)
        self.engine = Engine(self.store, [card])
        self.series = Series(self.store, self.engine)

    def tearDown(self):
        self.temp.cleanup()

    def book(self, text=TEXT, suffix=".txt", raw=None):
        path = self.root / ("source-fixture" + suffix)
        path.write_bytes(raw if raw is not None else text.encode())
        return self.library.import_book(path, "The Lighthouse", "owned")

    def fake_writer(self, card, prompt, dependencies, directory, key=""):
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / "content.md"
        output.write_text("Explicitly simulated creative output for a source/series test.")
        return output

    def complete(self, run):
        with patch.object(adapters, "execute", self.fake_writer):
            self.engine.execute(run)
        self.engine.approve(run)

    def test_txt_heading_order_and_source_provenance(self):
        book = self.book()
        self.assertEqual(len(book["units"]), 2)
        self.assertNotIn("text", book["units"][0])
        context = self.library.context(book["id"], 1)
        self.assertEqual(context["source"]["index"], 1)
        self.assertIn("small mirror", context["source"]["text"])
        self.assertNotIn(str(self.root), json.dumps(book))
        self.assertNotIn("source-fixture", (self.store.root / "loom.sqlite3").read_bytes().decode(errors="replace"))

    def test_cli_import_inspect_and_create_series_at_explicit_start_unit(self):
        path = self.root / "fixture.txt"
        path.write_text(TEXT)
        def cli(*args):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--data", str(self.store.root), *args]), 0)
            return json.loads(output.getvalue())
        book = cli("book-import", str(path), "--title", "Fixture", "--rights", "owned")
        unit = cli("book-inspect", book["id"], "--unit", "1")
        self.assertIn("small mirror", unit["source"]["text"])
        series = cli("series-new", book["id"], "Adapt this book", "--start-unit", "1")
        self.assertEqual(series["cursor"], 1)
        with self.assertRaisesRegex(ValueError, "start_unit"):
            self.series.create(book["id"], Brief("Invalid start"), start_unit=99)

    def test_chinese_and_bom_text_decodings(self):
        text = "序章\n灯塔等待来信。\n第一章 蓝色的信号\n守塔人看见了光。\n第二章 回答\n镜子闪了一下。"
        for encoding in ["utf-8-sig", "utf-16", "gb18030"]:
            book = self.book(raw=text.encode(encoding))
            self.assertEqual(len(book["units"]), 3)
            self.assertIn("镜子", self.library.context(book["id"], 2)["source"]["text"])

    def test_long_chapters_split_without_losing_non_whitespace_text(self):
        text = "Chapter 1\n" + ("The lighthouse shines. " * 100)
        source = self.root / "long.txt"
        source.write_text(text)
        book = self.library.import_book(source, "Long fixture", "owned", unit_chars=200)
        units = self.library.book(book["id"])["units"]
        self.assertGreater(len(units), 5)
        self.assertTrue(all(len(u["text"]) <= 200 for u in units))
        self.assertEqual("".join("".join(u["text"].split()) for u in units), "".join(text.split()))
        self.assertEqual([u["index"] for u in units], list(range(len(units))))

    def test_empty_sources_rights_and_unsupported_formats_are_rejected(self):
        with self.assertRaises(ValueError):
            self.book(" \n \t")
        path = self.root / "test.txt"
        path.write_text(TEXT)
        with self.assertRaisesRegex(ValueError, "rights"):
            self.library.import_book(path, "Book", "unspecified")
        with self.assertRaisesRegex(ValueError, "unit_chars"):
            self.library.import_book(path, "Book", "owned", unit_chars=True)
        unsupported = self.root / "test.pdf"
        unsupported.write_bytes(b"placeholder")
        with self.assertRaisesRegex(ValueError, "TXT"):
            self.library.import_book(unsupported, "Book", "owned")

    def test_epub_uses_spine_order_and_preserves_visible_license(self):
        book = self.book(suffix=".epub", raw=epub())
        self.assertIn("Chapter 2", book["units"][0]["title"])
        context = self.library.context(book["id"], 1)
        self.assertIn("Fixture license: MIT", context["source"]["text"])
        self.assertNotIn("Hidden metadata", context["source"]["text"])
        self.assertNotIn("Do not execute", context["source"]["text"])

    def test_epub_external_and_traversing_references_are_rejected(self):
        for href in ["../outside.xhtml", "%2e%2e/outside.xhtml", "/outside.xhtml", "https://example.com/a.xhtml"]:
            with self.assertRaises(ValueError):
                epub_sections(epub(href=href))
        self.assertFalse((self.root / "outside.xhtml").exists())

    def test_epub_dtd_encryption_duplicate_spine_and_size_limits(self):
        dtd = '<?xml version="1.0"?><!DOCTYPE container [<!ENTITY bad "value">]><container/>'
        for raw in [epub(encryption=True), epub(spine="a a"),
                    epub(container_override=dtd.encode("utf-16")), b"not-a-zip"]:
            with self.assertRaises(ValueError):
                epub_sections(raw)
        with patch("creator_loom.library.MAX_UNPACKED", 100):
            with self.assertRaisesRegex(ValueError, "uncompressed"):
                epub_sections(epub())

    def test_source_snapshot_and_continuity_are_in_actual_text_prompts(self):
        book = self.book()
        context = self.library.context(book["id"], 1, "The keeper has not left the tower.")
        plan = self.engine.plan(Brief("Adapt each chapter", "novel"), context=context)
        self.assertIn("small mirror", plan["steps"][1]["prompt"])
        self.assertIn("has not left", plan["steps"][1]["prompt"])
        self.assertIn("Do not restart", plan["steps"][1]["prompt"])
        self.assertEqual(plan["context"]["source"]["sha256"], context["source"]["sha256"])

    def test_tampered_source_blocks_execution_before_adapter_call(self):
        book = self.book()
        run = self.engine.create(Brief("Adapt source"), context=self.library.context(book["id"]))
        (self.store.root / "library" / book["id"] / "source.bin").write_bytes(b"changed")
        with patch.object(adapters, "execute") as call:
            with self.assertRaisesRegex(ValueError, "source is missing or changed"):
                self.engine.execute(run)
            call.assert_not_called()
        self.assertEqual(self.store.run(run)["status"], "ready")

    def test_imported_unit_tampering_is_detected(self):
        book = self.book()
        units = self.library.book(book["id"])["units"]
        units[0]["text"] = "Changed without updating provenance"
        with self.store.connect() as db:
            db.execute("UPDATE books SET units=? WHERE id=?", (json.dumps(units), book["id"]))
        with self.assertRaisesRegex(ValueError, "chapter text changed"):
            self.library.context(book["id"])

    def test_series_next_is_idempotent_even_under_concurrent_calls(self):
        book = self.book()
        series = self.series.create(book["id"], Brief("Adapt chapters"))
        with ThreadPoolExecutor(max_workers=4) as executor:
            runs = list(executor.map(lambda _: self.series.next(series["id"]), range(8)))
        self.assertEqual(len(set(runs)), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM series_episodes").fetchone()[0], 1)

    def test_concurrent_acceptance_advances_cursor_only_once(self):
        book = self.book()
        series = self.series.create(book["id"], Brief("Adapt chapters"))
        run = self.series.next(series["id"])
        self.complete(run)
        def accept():
            try:
                self.series.accept(series["id"], run, "A keeper sees a signal.", 1)
                return "accepted"
            except ValueError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: accept(), range(2)))
        self.assertEqual(sorted(outcomes), ["accepted", "conflict"])
        self.assertEqual(self.series.inspect(series["id"])["cursor"], 1)

    def test_schema_upgrade_preserves_prior_run_rows(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        with sqlite3.connect(legacy / "loom.sqlite3") as db:
            db.execute("CREATE TABLE runs(id TEXT PRIMARY KEY,brief TEXT NOT NULL,plan TEXT NOT NULL,status TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("INSERT INTO runs(id,brief,plan,status) VALUES('legacy','{}','{}','approved')")
        upgraded = Store(legacy)
        self.assertEqual(upgraded.run("legacy")["status"], "approved")
        with upgraded.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM books").fetchone()[0], 0)

    def test_series_advances_only_approved_episodes_and_freezes_continuity(self):
        book = self.book()
        series = self.series.create(book["id"], Brief("Adapt chapters", "novel"))
        first = self.series.next(series["id"])
        with self.assertRaisesRegex(ValueError, "Approve"):
            self.series.accept(series["id"], first, "Keeper sees a blue signal.", 1)
        self.complete(first)
        state = self.series.accept(series["id"], first, "Keeper sees a blue signal.", 1)
        self.assertEqual((state["cursor"], state["version"]), (1, 2))
        second = self.series.next(series["id"])
        self.assertEqual(self.store.run(second)["plan"]["context"]["continuity"], "Keeper sees a blue signal.")
        self.assertEqual(self.store.run(first)["plan"]["context"]["continuity"], "")
        with self.assertRaisesRegex(ValueError, "version"):
            self.series.accept(series["id"], second, "Stale edit", 1)
        self.complete(second)
        state = self.series.accept(series["id"], second, "Keeper answers using a mirror.", 2)
        self.assertTrue(state["completed"])
        with self.assertRaisesRegex(ValueError, "all imported units"):
            self.series.next(series["id"])

    def test_changed_approved_artifact_cannot_advance_series(self):
        book = self.book()
        series = self.series.create(book["id"], Brief("Adapt chapters"))
        run = self.series.next(series["id"])
        self.complete(run)
        state = self.store.run(run)
        self.engine.artifact(run, state["steps"][0]["result"]).write_text("Replaced after review")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.series.accept(series["id"], run, "Any notes", 1)
        self.assertEqual(self.series.inspect(series["id"])["cursor"], 0)

    def test_rejecting_unexecuted_episode_cancels_it_and_keeps_same_source_unit(self):
        book = self.book()
        series = self.series.create(book["id"], Brief("Adapt chapters"))
        first = self.series.next(series["id"])
        self.series.reject(series["id"], first, 1, "Change the model configuration before execution.")
        self.assertEqual(self.store.run(first)["status"], "cancelled")
        with self.assertRaises(ValueError):
            self.engine.execute(first)
        second = self.series.next(series["id"])
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.run(second)["plan"]["context"]["source"]["index"], 0)

    def test_uncertain_episode_requires_explicit_provider_reconciliation(self):
        book = self.book()
        series = self.series.create(book["id"], Brief("Adapt chapters"))
        run = self.series.next(series["id"])
        with patch.object(adapters, "execute", side_effect=adapters.ProviderUncertain("Unknown outcome")):
            with self.assertRaises(ValueError):
                self.engine.execute(run)
        with self.assertRaisesRegex(ValueError, "reconciliation"):
            self.series.reject(series["id"], run, 1, "Review the provider job before making another attempt.")
        state = self.series.reject(series["id"], run, 1, "Provider checked; retain original attempt for audit.", True)
        self.assertIsNone(state["pending_run"])
        self.assertEqual(self.store.run(run)["steps"][0]["status"], "uncertain")

    def test_running_episode_cannot_be_detached(self):
        book = self.book()
        series = self.series.create(book["id"], Brief("Adapt chapters"))
        run = self.series.next(series["id"])
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status='executing' WHERE id=?", (run,))
        with self.assertRaisesRegex(ValueError, "running episode"):
            self.series.reject(series["id"], run, 1, "Do not detach a live or unreconciled worker.", True)

    def test_technique_evaluation_rejects_different_source_units(self):
        book = self.book()
        learning = Learning(self.store, self.engine)
        learning.propose("details", "https://example.com/research", "Use concrete details.")
        brief = Brief("Identical topic")
        baseline = self.engine.create(brief, context=self.library.context(book["id"], 0))
        candidate = self.engine.create(brief, "details", self.library.context(book["id"], 1))
        self.complete(baseline)
        self.complete(candidate)
        pair = {"baseline": baseline, "candidate": candidate, "baseline_score": 0.5,
                "candidate_score": 0.8, "rationale": "Different source units must not count as a controlled trial."}
        with self.assertRaisesRegex(ValueError, "source and continuity"):
            learning.evaluate("details", [pair] * 3)
