"""Real HTTP tests for the authenticated local workbench and deliverable export."""

import base64
import hashlib
import http.client
import io
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from contextlib import closing
import wave
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

    def timeline_fixture(self, name="edit"):
        self.login()
        _, run = self.cover()
        self.run_action(run)
        self.api("POST", f"/api/runs/{run}/approve", {})
        assets = self.api("GET", "/api/timeline-assets?profile=default")["assets"]
        source = next(a for a in assets if a["ref"]["run"] == run)
        spec = {"title": "Original HTTP edit", "width": 640, "height": 360, "fps": 24,
                "shots": [{"id": "opening", "source": source["ref"], "duration": 0.5}],
                "captions": [{"start": 0, "end": 0.5, "text": "An original cue, with a comma."}]}
        key = uuid.uuid4().hex
        timeline = self.api("POST", "/api/timelines", {"id": name, "spec": spec, "profile": "default"}, {"Idempotency-Key": key})
        return timeline, source, key

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
    def test_timeline_http_review_render_caption_preview_and_export(self):
        timeline, source, key = self.timeline_fixture()
        preview = self.api("GET", "/api/timeline-assets/"+source["key"])
        self.assertEqual(preview["kind"], "image")
        status, headers, raw = self.request("GET", preview["preview"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(self.api("GET", "/api/timelines?profile=default")[0]["id"], "edit")
        self.assertEqual(self.api("GET", "/api/timelines?profile=other"), [])
        self.assertEqual(self.request("POST", "/api/timelines/edit/render", {"version": 1}, {"Idempotency-Key": "too-early"})[0], 409)
        self.assertEqual(self.request("GET", "/api/timeline-media/edit/1/film.mp4")[0], 409)
        review = {"version": 1, "shot": "opening", "decision": "approve", "note": "Original framing and rights reviewed."}
        self.api("POST", "/api/timelines/edit/shot", review)
        self.assertEqual(len(self.api("POST", "/api/timelines/edit/shot", review)["reviews"]), 1)
        self.api("POST", "/api/timelines/edit/seal", {"version": 1})
        self.api("POST", "/api/timelines/edit/seal", {"version": 1})
        render_key = uuid.uuid4().hex
        action = self.api("POST", "/api/timelines/edit/render", {"version": 1}, {"Idempotency-Key": render_key})
        repeated = self.api("POST", "/api/timelines/edit/render", {"version": 1}, {"Idempotency-Key": render_key})
        self.assertEqual(repeated["id"], action["id"])
        for _ in range(100):
            result = self.api("GET", "/api/timelines/edit?version=1")
            if result["actions"][0]["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        self.assertEqual(result["state"], "needs_review")
        self.assertEqual(result["actions"][0]["status"], "done")
        status, headers, raw = self.request("GET", "/api/timeline-media/edit/1/film.mp4", headers={"Range": "bytes=0-31"})
        self.assertEqual(status, 206)
        self.assertEqual(len(raw), 32)
        self.assertIn(b"ftyp", raw)
        status, headers, raw = self.request("GET", "/api/timeline-media/edit/1/captions.vtt")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/vtt; charset=utf-8")
        self.assertIn(b"00:00:00.000 --> 00:00:00.500", raw)
        self.assertIn(b"cue, with a comma", raw)
        self.assertEqual(self.request("GET", "/api/timeline-export/edit/1")[0], 409)
        self.api("POST", "/api/timelines/edit/approve", {"version": 1})
        self.api("POST", "/api/timelines/edit/approve", {"version": 1})
        status, headers, raw = self.request("GET", "/api/timeline-export/edit/1")
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()), {"film.mp4", "timeline.json", "captions.srt"})
            self.assertNotIn(source["ref"]["run"], archive.read("timeline.json").decode())
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM web_timeline_actions").fetchone()[0], 1)
        film = self.server.app.timeline.directory("edit", 1)/"film.mp4"
        film.write_bytes(b"Changed render")
        for path in ["/api/timeline-media/edit/1/film.mp4", "/api/timeline-media/edit/1/captions.vtt", "/api/timeline-export/edit/1"]:
            self.assertEqual(self.request("GET", path)[0], 409)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
    def test_timeline_mutations_are_persistently_idempotent_and_preserve_history(self):
        timeline, source, key = self.timeline_fixture()
        spec = timeline["spec"]
        repeated = self.api("POST", "/api/timelines", {"id": "edit", "spec": spec, "profile": "default"}, {"Idempotency-Key": key})
        self.assertEqual(repeated["version"], 1)
        spec = json.loads(json.dumps(spec)); spec["title"] = "Revised original edit"
        revision_key = uuid.uuid4().hex
        body = {"version": 1, "spec": spec}
        self.assertEqual(self.api("POST", "/api/timelines/edit/revise", body, {"Idempotency-Key": revision_key})["version"], 2)
        self.assertEqual(self.api("POST", "/api/timelines/edit/revise", body, {"Idempotency-Key": revision_key})["version"], 2)
        self.assertEqual(self.request("POST", "/api/timelines/edit/revise", body, {"Idempotency-Key": uuid.uuid4().hex})[0], 409)
        self.assertEqual(self.api("GET", "/api/timelines/edit?version=1")["spec"]["title"], "Original HTTP edit")
        spec["title"] = "Different request with same key"
        self.assertEqual(self.request("POST", "/api/timelines/edit/revise", body, {"Idempotency-Key": revision_key})[0], 409)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM timeline_versions").fetchone()[0], 2)
        self.assertEqual(self.request("POST", "/api/timelines", {"id": "missing-key", "spec": spec})[0], 409)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
    def test_timeline_sources_are_scoped_verified_and_new_routes_require_auth(self):
        timeline, source, _ = self.timeline_fixture()
        other_engine = Engine(self.store, load_cards(None))
        other = other_engine.create(Brief("Other preference fixture", "cover", profile="other", local_only=True))
        other_engine.execute(other); other_engine.approve(other)
        self.assertTrue(all(a["ref"]["run"] != other for a in self.api("GET", "/api/timeline-assets")["assets"]))
        self.assertEqual(len(self.api("GET", "/api/timeline-assets?profile=other")["assets"]), 1)
        for path in ["/api/timelines", "/api/timeline-assets", "/api/timeline-previews/"+source["key"], "/api/timeline-media/edit/1/film.mp4", "/api/timeline-export/edit/1"]:
            self.assertEqual(self.request("GET", path, auth=False)[0], 401)
            self.assertEqual(self.request("GET", path, headers={"Origin": "https://example.com"})[0], 403)
        run = self.store.run(source["ref"]["run"])
        self.server.app.engine.artifact(run["id"], run["steps"][0]["result"]).write_bytes(b"changed source")
        self.assertEqual(self.api("GET", "/api/timeline-assets")["unavailable_runs"], 1)
        self.assertEqual(self.request("GET", "/api/timeline-assets/"+source["key"])[0], 409)
        self.assertEqual(self.request("GET", "/api/timeline-previews/"+source["key"])[0], 409)
        self.assertEqual(self.request("POST", "/api/timelines/edit/shot", {"version": 1, "shot": "opening", "decision": "approve", "note": "Changed source must block review."})[0], 409)

    def test_timeline_legacy_profile_migration_and_non_replayed_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            with closing(sqlite3.connect(Path(temporary)/"loom.sqlite3")) as db, db:
                db.execute("CREATE TABLE timelines(id TEXT PRIMARY KEY,current_version INTEGER NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP)")
                db.execute("INSERT INTO timelines(id,current_version) VALUES('legacy',1)")
            migrated = Store(Path(temporary))
            with migrated.connect() as db:
                self.assertEqual(db.execute("SELECT profile FROM timelines WHERE id='legacy'").fetchone()[0], "default")
        with self.store.connect() as db:
            db.execute("INSERT INTO web_timeline_actions VALUES('interrupted-edit','missing',1,'queued',NULL)")
        from creator_loom.workbench import Workbench
        with patch("creator_loom.timeline.Timeline.render", side_effect=AssertionError("No replay")):
            fresh = Workbench(self.store, load_cards(None))
            fresh.pool.shutdown(wait=True)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM web_timeline_actions WHERE id='interrupted-edit'").fetchone()[0], "interrupted")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
    def test_queued_timeline_render_cannot_target_a_new_revision(self):
        timeline, source, _ = self.timeline_fixture()
        self.api("POST", "/api/timelines/edit/shot", {"version": 1, "shot": "opening", "decision": "approve", "note": "Source and timing reviewed."})
        self.api("POST", "/api/timelines/edit/seal", {"version": 1})
        key = uuid.uuid4().hex
        with patch.object(self.server.app.pool, "submit") as submit:
            self.api("POST", "/api/timelines/edit/render", {"version": 1}, {"Idempotency-Key": key})
            self.assertEqual(submit.call_count, 1)
        spec = timeline["spec"]; spec["title"] = "A newer explicit edit"
        self.api("POST", "/api/timelines/edit/revise", {"version": 1, "spec": spec}, {"Idempotency-Key": uuid.uuid4().hex})
        with patch("creator_loom.timeline_media.render", side_effect=AssertionError("No stale rendering")):
            self.server.app._render_timeline(key, "edit", 1)
        self.assertEqual(self.api("GET", "/api/timelines/edit")["state"], "draft")
        old = self.api("GET", "/api/timelines/edit?version=1")
        self.assertEqual(old["state"], "sealed")
        self.assertEqual(old["actions"][0]["status"], "error")
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT outputs FROM timeline_versions WHERE timeline_id='edit' AND version=2").fetchone()[0])

    def media_audio(self, origin=None, key=None):
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0"*24000)
        metadata = {"title": "Original HTTP audio fixture", "kind": "audio", "rights": "owned", "rights_note": "Original synthetic audio, authorized for fixture reuse.", "authorized": True, "profile": "default"}
        if origin:
            metadata["origin"] = origin
        body = {"data": base64.b64encode(stream.getvalue()).decode(), "metadata": metadata}
        request_key = key or uuid.uuid4().hex
        return self.api("POST", "/api/assets", body, {"Idempotency-Key": request_key}), body, request_key

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
    def test_authorized_media_http_import_review_and_timeline_sources(self):
        self.login()
        asset, body, key = self.media_audio()
        repeated = self.api("POST", "/api/assets", body, {"Idempotency-Key": key})
        self.assertEqual(asset["id"], repeated["id"])
        media_path = f"/api/assets/{asset['id']}/media"
        self.assertEqual(self.request("GET", media_path, auth=False)[0], 401)
        self.assertEqual(self.request("GET", media_path, headers={"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("GET", f"/api/assets/{asset['id']}/export")[0], 409)
        self.assertFalse(any(a["ref"].get("asset") == asset["id"] for a in self.api("GET", "/api/timeline-assets")["assets"]))
        self.api("POST", f"/api/assets/{asset['id']}/review", {"decision": "approve", "note": "Actual audio and source rights checked."})
        source = next(a for a in self.api("GET", "/api/timeline-assets")["assets"] if a["ref"].get("asset") == asset["id"])
        info = self.api("GET", "/api/timeline-assets/"+source["key"])
        self.assertEqual(info["kind"], "audio")
        self.assertAlmostEqual(info["duration"], 0.5)
        status, headers, raw = self.request("GET", info["preview"], headers={"Range": "bytes=0-15"})
        self.assertEqual(status, 206)
        self.assertTrue(raw.startswith(b"RIFF"))
        status, headers, raw = self.request("GET", f"/api/assets/{asset['id']}/export")
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()), {"audio.wav", "credits.json"})
            self.assertNotIn("rights_note", archive.read("credits.json").decode())
        body["metadata"]["authorized"] = False
        self.assertEqual(self.request("POST", "/api/assets", body, {"Idempotency-Key": uuid.uuid4().hex})[0], 409)
        self.assertEqual(self.request("POST", "/api/assets", {}, {"Content-Length": str(46*1024*1024+1)})[0], 413)
        _, path = self.server.app.assets.verify(asset["id"])
        path.write_bytes(b"changed")
        self.assertEqual(self.request("GET", media_path)[0], 409)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
    def test_music_http_plan_explicit_handoff_and_reported_result_adoption(self):
        self.login()
        source, _, _ = self.media_audio()
        self.api("POST", f"/api/assets/{source['id']}/review", {"decision": "approve", "note": "Original source and reuse checked."})
        self.server.app.cards.append(ModelCard("music-writer", "text", "chat", model="fixture", local=True, endpoint="http://127.0.0.1:8765/v1", max_chars=30000))
        spec = {"title": "Original music brief", "intent": "Create a gentle original lyric and arrangement direction.", "lyrics": "A quiet lantern by the sea.", "lyrics_rights": "owned", "rights_note": "Original test text and authorized synthetic audio.", "adaptation_authorized": True, "source": {"asset": source["id"]}}
        key = uuid.uuid4().hex
        project = self.api("POST", "/api/music", {"id": "music-fixture", "spec": spec}, {"Idempotency-Key": key})
        self.assertEqual(self.api("POST", "/api/music", {"id": "music-fixture", "spec": spec}, {"Idempotency-Key": key})["run_id"], project["run_id"])
        self.assertEqual(self.request("GET", "/api/music/music-fixture/handoff")[0], 409)
        def fake_text(card, prompt, dependencies, directory, key=""):
            directory.mkdir(parents=True, exist_ok=True)
            path = directory/"content.md"; path.write_text("Original simulated music planning text."); return path
        with patch.object(adapters, "execute", fake_text):
            self.run_action(project["run_id"])
        self.api("POST", f"/api/runs/{project['run_id']}/approve", {})
        decision = {"transfer_authorized": False, "include_audio": True, "note": "Authorize exactly this reference for the local package."}
        self.assertEqual(self.request("POST", "/api/music/music-fixture/handoff", decision)[0], 409)
        decision["transfer_authorized"] = True
        self.api("POST", "/api/music/music-fixture/handoff", decision)
        status, headers, raw = self.request("GET", "/api/music/music-fixture/handoff")
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn("reference.wav", archive.namelist())
            self.assertNotIn("rights_note", archive.read("brief.json").decode())
        reference = "https://suno.com/song/12345678-1234-1234-1234-123456789abc"
        external = self.api("POST", "/api/music/music-fixture/external", {"reference": reference, "note": "Operator reports this external result, without API proof."})
        self.assertIn("not verified", external["external"]["evidence"])
        result, _, _ = self.media_audio({"service": "suno", "reference": reference})
        self.assertEqual(self.request("POST", "/api/music/music-fixture/attach", {"asset": result["id"], "note": "Unreviewed audio cannot be adopted."})[0], 409)
        self.api("POST", f"/api/assets/{result['id']}/review", {"decision": "approve", "note": "Actual audio, credits and rights checked."})
        attached = self.api("POST", "/api/music/music-fixture/attach", {"asset": result["id"], "note": "Reviewed local result adopted for this brief."})
        self.assertEqual(attached["state"], "result_attached")
        self.assertIn("operator-reported", attached["result"]["evidence"])
