"""Real HTTP tests for the authenticated local workbench and deliverable export."""

import base64
import hashlib
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.routing import load_cards
from creator_loom.store import Store
from creator_loom.workbench import create_server


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.server = create_server(self.store, load_cards(None), 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ""

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None, auth=True):
        h = {"Content-Type": "application/json", "X-Loom-Request": "1"}
        if auth and self.cookie:
            h["Cookie"] = self.cookie
        h.update(headers or {})
        raw = json.dumps(body).encode() if body is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=raw, headers=h)
            response = connection.getresponse()
            data = response.read()
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def api(self, method, path, body=None, headers=None):
        status, h, raw = self.request(method, path, body, headers)
        self.assertEqual(status, 200, raw.decode(errors="replace"))
        return json.loads(raw)

    def login(self):
        status, headers, raw = self.request("POST", "/api/session", {"code": self.server.code})
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        return headers

    def cover(self):
        draft = self.api("POST", "/api/plans", {"brief": {"topic": "Original ocean reading cover", "format": "cover", "local_only": True, "budget": 0}})
        run = self.api("POST", "/api/runs", {"draft": draft["draft"]}, {"Idempotency-Key": uuid.uuid4().hex})["run"]
        return draft, run

    def run_action(self, run, key=None):
        key = key or uuid.uuid4().hex
        action = self.api("POST", f"/api/runs/{run}/execute", {}, {"Idempotency-Key": key})
        for _ in range(100):
            state = self.api("GET", "/api/actions/"+action["id"])
            if state["status"] not in {"queued", "running"}:
                self.assertEqual(state["status"], "done")
                return state
            time.sleep(0.02)
        self.fail("Background action did not finish")

    def test_private_data_requires_session_and_static_html_contains_no_secret(self):
        self.assertEqual(self.request("GET", "/api/overview")[0], 401)
        status, headers, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn(self.server.code.encode(), html)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("POST", "/api/session", {"code": "wrong"})[0], 401)
        headers = self.login()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(self.api("GET", "/api/session")["authenticated"], True)

    def test_cross_origin_dns_rebinding_and_mutation_without_custom_header_are_rejected(self):
        self.login()
        self.assertEqual(self.request("GET", "/api/overview", headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/api/overview", headers={"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("POST", "/api/plans", {}, {"X-Loom-Request": ""})[0], 403)
        self.assertEqual(self.request("POST", "/api/plans", {}, {"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_preview_is_frozen_and_create_is_persistently_idempotent(self):
        self.login()
        self.store.set_preferences("default", {"tone": "calm"})
        draft = self.api("POST", "/api/plans", {"brief": {"topic": "A cover", "format": "cover"}})
        self.store.set_preferences("default", {"tone": "changed after preview"})
        key = uuid.uuid4().hex
        first = self.api("POST", "/api/runs", {"draft": draft["draft"]}, {"Idempotency-Key": key})
        second = self.api("POST", "/api/runs", {"draft": draft["draft"]}, {"Idempotency-Key": key})
        self.assertEqual(first, second)
        self.assertEqual(self.store.run(first["run"])["plan"]["preferences"]["tone"], "calm")
        self.assertEqual(self.request("POST", "/api/runs", {"draft": "another"}, {"Idempotency-Key": key})[0], 409)

    def test_cover_creation_preview_review_and_export_over_real_http(self):
        self.login()
        _, run = self.cover()
        key = uuid.uuid4().hex
        with patch.object(self.server.app.engine, "execute", wraps=self.server.app.engine.execute) as call:
            self.run_action(run, key)
            self.api("POST", f"/api/runs/{run}/execute", {}, {"Idempotency-Key": key})
            self.assertEqual(call.call_count, 1)
        state = self.api("GET", "/api/runs/"+run)
        self.assertEqual(state["status"], "needs_review")
        status, headers, svg = self.request("GET", f"/api/artifacts/{run}/cover/s0")
        self.assertEqual(status, 200)
        self.assertIn(b"<svg", svg)
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/api/export/"+run)[0], 409)
        self.api("POST", f"/api/runs/{run}/approve", {})
        self.api("POST", f"/api/runs/{run}/approve", {})
        status, _, archive = self.request("GET", "/api/export/"+run)
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertNotIn("profile", manifest)
            self.assertNotIn("plan", manifest)
            self.assertTrue(all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in bundle.infolist()))
            for item in manifest["files"]:
                self.assertEqual(hashlib.sha256(bundle.read(item["name"])).hexdigest(), item["sha256"])

    def test_range_playback_suffix_range_and_path_traversal(self):
        self.login()
        _, run = self.cover()
        self.run_action(run)
        path = f"/api/artifacts/{run}/cover/s0"
        full = self.request("GET", path)[2]
        status, headers, data = self.request("GET", path, headers={"Range": "bytes=0-19"})
        self.assertEqual(status, 206)
        self.assertEqual(data, full[:20])
        self.assertIn("bytes 0-19/", headers["Content-Range"])
        self.assertEqual(self.request("GET", path, headers={"Range": "bytes=-6"})[2], full[-6:])
        self.assertEqual(self.request("GET", path, headers={"Range": "bytes=99999999-"})[0], 416)
        self.assertNotEqual(self.request("GET", "/api/artifacts/../../secret")[0], 200)
        self.assertEqual(self.request("GET", f"/api/artifacts/{run}/absent/main")[0], 409)

    def test_artifact_tampering_blocks_preview_approval_and_delivery(self):
        self.login()
        _, run = self.cover()
        self.run_action(run)
        result = self.store.run(run)["steps"][0]["result"]
        self.server.app.engine.artifact(run, result).write_bytes(b"changed")
        self.assertEqual(self.request("GET", f"/api/artifacts/{run}/cover/main")[0], 409)
        self.assertEqual(self.request("POST", f"/api/runs/{run}/approve", {})[0], 409)

    def test_operational_metadata_is_excluded_and_timings_are_allowlisted(self):
        self.login()
        _, run = self.cover()
        execute = adapters.execute
        def with_operational_metadata(card, prompt, dependencies, directory, key=""):
            output = execute(card, prompt, dependencies, directory, key)
            (directory/"mediaflow.json").write_text(json.dumps({"job_ids": ["private-job-fixture"]}))
            (directory/"provider-usage.json").write_text(json.dumps({"status": "not_reported"}))
            (directory/"internal-receipt.json").write_text(json.dumps({"internal": "private-sidecar-fixture"}))
            (directory/"timings.json").write_text(json.dumps({"segments": [{"start": 0, "end": 1, "text": "Original fixture narration", "job_id": "private-job-fixture"}]}))
            return output
        with patch.object(adapters, "execute", with_operational_metadata):
            self.run_action(run)
        self.api("POST", f"/api/runs/{run}/approve", {})
        raw = self.request("GET", "/api/export/"+run)[2]
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            self.assertFalse(any(name.endswith(("mediaflow.json", "provider-usage.json")) for name in bundle.namelist()))
            self.assertFalse(any(name.endswith("internal-receipt.json") for name in bundle.namelist()))
            timings = json.loads(bundle.read("cover/timings.json"))
            self.assertNotIn("job_id", timings["segments"][0])
            self.assertNotIn("private-job-fixture", "".join(bundle.read(n).decode(errors="replace") for n in bundle.namelist()))

    def test_book_upload_source_inspection_and_series_creation(self):
        self.login()
        book = self.api("POST", "/api/books", {"format": "txt", "title": "Original fixture", "rights": "owned",
                          "data": base64.b64encode(b"Chapter 1\nA signal.\nChapter 2\nA mirror.").decode()})
        self.assertEqual(len(book["units"]), 2)
        excerpt = self.api("GET", f"/api/books/{book['id']}?unit=1")
        self.assertIn("mirror", excerpt["source"]["text"])
        series = self.api("POST", "/api/series", {"book": book["id"], "brief": {"topic": "Adapt source", "format": "article"}})
        self.assertEqual(series["cursor"], 0)
        overview = self.api("GET", "/api/overview")
        self.assertEqual(overview["books"][0]["units"], 2)
        self.assertNotIn("data", overview["books"][0])

    def test_expired_preview_and_oversized_requests_fail_before_mutation(self):
        self.login()
        draft = self.api("POST", "/api/plans", {"brief": {"topic": "Cover", "format": "cover"}})
        with self.store.connect() as db:
            db.execute("UPDATE web_drafts SET expires=0 WHERE id=?", (draft["draft"],))
        self.assertEqual(self.request("POST", "/api/runs", {"draft": draft["draft"]}, {"Idempotency-Key": uuid.uuid4().hex})[0], 409)
        self.assertEqual(self.request("POST", "/api/books", {}, {"Content-Length": str(13*1024*1024)})[0], 413)

    def test_single_workbench_owner(self):
        with self.assertRaisesRegex(ValueError, "lock"):
            create_server(self.store, load_cards(None), 0)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_restart_retains_interrupted_actions_without_automatic_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            run = Engine(store, load_cards(None)).create(Brief("Unexecuted original fixture", "cover"))
            with store.connect() as db:
                db.execute("INSERT INTO web_actions VALUES('prior-action',?,'execute','running',NULL)", (run,))
            server = create_server(store, load_cards(None), 0)
            try:
                with store.connect() as db:
                    self.assertEqual(db.execute("SELECT status FROM web_actions").fetchone()[0], "interrupted")
                self.assertEqual(store.run(run)["status"], "ready")
                self.assertEqual(store.run(run)["steps"][0]["status"], "pending")
            finally:
                server.server_close()

    def test_text_coaching_revision_and_progress_over_http(self):
        self.login()
        self.server.app.cards.append(ModelCard("test-writer", "text", "chat", model="fixture", endpoint="http://127.0.0.1:8765/v1", local=True))
        draft = self.api("POST", "/api/plans", {"brief": {"topic": "Original text fixture", "format": "article"}})
        run = self.api("POST", "/api/runs", {"draft": draft["draft"]}, {"Idempotency-Key": uuid.uuid4().hex})["run"]
        def fake_text(card, prompt, dependencies, directory, key=""):
            directory.mkdir(parents=True, exist_ok=True)
            output = directory/"content.md"
            output.write_text("Original test draft.")
            return output
        with patch.object(adapters, "execute", fake_text):
            self.run_action(run)
        workbook = self.api("POST", f"/api/runs/{run}/coach", {})
        self.assertIn("clarity", workbook["stages"][0]["rubric"])
        revision = {"step": "draft", "revision": "A revised draft with a concrete example.", "dimension": "clarity", "before": 0.4, "after": 0.6,
                    "rationale": "Added a concrete example so the main idea is easier to understand."}
        result = self.api("POST", f"/api/runs/{run}/practice", revision)
        self.assertAlmostEqual(result["delta"], 0.2)
        progress = self.api("GET", "/api/overview")["progress"]
        self.assertEqual(progress["dimensions"][0]["attempts"], 1)

    def test_expired_session_can_be_reconnected_without_exposing_secret(self):
        self.login()
        self.server.expires = 0
        self.assertEqual(self.request("GET", "/api/overview")[0], 401)
        self.login()
        self.assertEqual(self.api("GET", "/api/session")["authenticated"], True)

    def test_reviewed_series_advances_once_and_exposes_current_revision(self):
        self.login()
        self.server.app.cards.append(ModelCard("test-writer", "text", "chat", model="fixture", endpoint="http://127.0.0.1:8765/v1", local=True))
        book = self.api("POST", "/api/books", {"format": "txt", "title": "Original series fixture", "rights": "owned",
                          "data": base64.b64encode(b"Chapter 1\nA signal.\nChapter 2\nA mirror.").decode()})
        series = self.api("POST", "/api/series", {"book": book["id"], "brief": {"topic": "Adapt the source", "format": "article"}})
        run = self.api("POST", f"/api/series/{series['id']}/next", {})["run"]
        def fake_text(card, prompt, dependencies, directory, key=""):
            directory.mkdir(parents=True, exist_ok=True)
            file = directory/"content.md"
            file.write_text("Explicitly simulated adaptation fixture.")
            return file
        with patch.object(adapters, "execute", fake_text):
            self.run_action(run)
        self.api("POST", f"/api/runs/{run}/approve", {})
        current = self.api("GET", "/api/series/"+series["id"])
        self.assertEqual(current["pending_run"], run)
        body = {"run": run, "version": 1, "continuity": "The keeper has observed a signal."}
        accepted = self.api("POST", f"/api/series/{series['id']}/accept", body)
        self.assertEqual((accepted["cursor"], accepted["version"]), (1, 2))
        self.assertEqual(self.request("POST", f"/api/series/{series['id']}/accept", body)[0], 409)
        next_run = self.api("POST", f"/api/series/{series['id']}/next", {})["run"]
        context = self.api("GET", "/api/runs/"+next_run)["plan"]["context"]
        self.assertEqual(context["source"]["index"], 1)
        self.assertIn("observed a signal", context["continuity"])
