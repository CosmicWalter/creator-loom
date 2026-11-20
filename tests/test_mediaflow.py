"""Actual HTTP with a simulated MediaFlow service tests remote effect handling."""

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
import wave
from contextlib import redirect_stdout
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.locking import run_lock
from creator_loom.mediaflow import Client, MediaFlow, split_text
from creator_loom.routing import load_cards
from creator_loom.store import Store
from creator_loom.cli import main


TEXT = "A lighthouse keeper sees a blue signal. A small mirror answers the signal."


def wav():
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0"*800)
    return data.getvalue()


class RemoteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.jobs, self.keys, self.uploads = {}, {}, []
        self.posts, self.writer_calls, self.downloads = 0, 0, 0
        self.completed, self.drop_submit, self.bad_download = False, False, False
        test = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, value, status=200):
                raw = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path == "/api/assets":
                    test.uploads.append(raw)
                    return self.send({"id": "a"*32}, 201)
                body = json.loads(raw)
                if self.path == "/v1/chat/completions":
                    test.writer_calls += 1
                    return self.send({"choices": [{"message": {"content": TEXT}}]})
                test.posts += 1
                key = self.headers.get("Idempotency-Key")
                if key not in test.keys:
                    job_id = uuid.uuid4().hex
                    test.keys[key] = job_id
                    test.jobs[job_id] = {"id": job_id, "kind": body["kind"], "source_id": body["source_id"],
                        "params": {k: body[k] for k in ["text", "prompt_text", "voice_authorized"]},
                        "status": "queued", "result": None}
                if test.drop_submit:
                    test.drop_submit = False
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send(test.jobs[test.keys[key]], 201)

            def do_GET(self):
                job_id = self.path.split("/")[3]
                job = test.jobs[job_id]
                if self.path.endswith("/files/speech.wav"):
                    test.downloads += 1
                    if test.bad_download:
                        test.bad_download = False
                        return self.send(b"not-a-wave")
                    return self.send(wav())
                if test.completed:
                    job.update(status="succeeded", result={"files": ["speech.wav"]})
                self.send(job)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        writer = ModelCard("writer", "text", "chat", model="simulated-writer", endpoint=self.endpoint+"/v1",
                           local=True, max_output_chars=500, max_chars=30000)
        self.speech = ModelCard("mediaflow", "audio", "mediaflow", model="indextts", endpoint=self.endpoint,
                               local=True, voice="a"*32, voice_authorized=True, segment_chars=40)
        self.engine = Engine(self.store, load_cards(None)+[writer, self.speech])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def start(self, format="podcast"):
        run = self.engine.create(Brief("Original lighthouse story", format, local_only=True))
        result = self.engine.execute(run)
        self.assertEqual(result["status"], "waiting_external")
        return run

    def test_persisted_job_resume_skips_writer_and_reuses_known_tasks(self):
        run = self.start()
        self.assertEqual(self.posts, 1)
        self.engine.resume(run)
        self.assertEqual(self.posts, 1)
        self.completed = True
        restarted = Engine(Store(self.store.root), self.engine.cards)
        result = restarted.resume(run)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(self.writer_calls, 1)
        batch = MediaFlow(self.store).load(run, "narration")
        self.assertEqual(self.posts, len(batch["segments"]))
        self.assertTrue(all(s["status"] == "done" for s in batch["segments"]))
        output = self.engine.artifact(run, result["steps"][-1]["result"])
        with wave.open(str(output), "rb") as audio:
            self.assertEqual(audio.getnframes(), 800*len(batch["segments"]))
        self.engine.approve(run)
        with self.assertRaises(ValueError):
            self.engine.resume(run)

    def test_lost_submit_response_never_posts_again_without_reconciliation(self):
        self.drop_submit = True
        run = self.start()
        for _ in range(2):
            result = self.engine.resume(run)
            self.assertEqual(result["waiting_reason"], "reconciliation_required")
        self.assertEqual(self.posts, 1)
        job = next(iter(self.jobs))
        self.engine.reconcile_mediaflow(run, "narration", 0, job)
        self.completed = True
        result = self.engine.resume(run)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(self.posts, len(split_text(TEXT, 40)))

    def test_reconciliation_requires_matching_frozen_request(self):
        self.drop_submit = True
        run = self.start()
        job = next(iter(self.jobs))
        self.jobs[job]["params"]["text"] = "An unrelated request"
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.engine.reconcile_mediaflow(run, "narration", 0, job)
        self.assertIsNone(MediaFlow(self.store).load(run, "narration")["segments"][0]["job_id"])

    def test_failed_download_retries_get_not_inference(self):
        run = self.start()
        self.completed, self.bad_download = True, True
        result = self.engine.resume(run)
        self.assertEqual(result["waiting_reason"], "download_unavailable")
        self.assertEqual(self.posts, 1)
        result = self.engine.resume(run)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(self.posts, len(split_text(TEXT, 40)))
        self.assertGreater(self.downloads, self.posts)

    def test_remote_failed_task_does_not_create_replacement(self):
        run = self.start()
        next(iter(self.jobs.values()))["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "uncertain"):
            self.engine.resume(run)
        with self.assertRaises(ValueError):
            self.engine.resume(run)
        self.assertEqual(self.posts, 1)
        self.assertEqual(MediaFlow(self.store).load(run, "narration")["segments"][0]["status"], "failed")

    def test_output_byte_limit_stops_before_submitting_later_segments(self):
        cards = [replace(c, segment_chars=20) if c.adapter == "mediaflow" else c for c in self.engine.cards]
        engine = Engine(self.store, cards)
        run = engine.create(Brief("A bounded podcast", "podcast"))
        self.completed = True
        with patch("creator_loom.mediaflow.MAX_BYTES", 3000):
            with self.assertRaisesRegex(ValueError, "uncertain"):
                engine.execute(run)
        self.assertEqual(self.posts, 2)
        self.assertLess(self.posts, len(split_text(TEXT, 20)))
        self.assertEqual(MediaFlow(self.store).load(run, "narration")["segments"][1]["status"], "oversized")

    def test_dead_worker_checkpoint_recovers_only_mediaflow(self):
        run = self.start()
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status='executing' WHERE id=?", (run,))
            db.execute("UPDATE steps SET status='running' WHERE run_id=? AND id='narration'", (run,))
        self.completed = True
        self.assertEqual(self.engine.resume(run)["status"], "needs_review")
        self.assertEqual(self.writer_calls, 1)

    def test_all_done_crash_window_finalizes_without_any_http(self):
        run = self.start()
        self.completed = True
        self.engine.resume(run)
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status='executing' WHERE id=?", (run,))
        with patch.object(Client, "request", side_effect=AssertionError("No remote request expected")):
            self.assertEqual(self.engine.resume(run)["status"], "needs_review")

    def test_wait_cli_stops_at_unknown_submission_instead_of_reposting(self):
        self.drop_submit = True
        run = self.start()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--data", str(self.store.root), "wait", run, "--timeout", "1"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["waiting_reason"], "reconciliation_required")
        self.assertEqual(self.posts, 1)

    def test_live_process_lock_prevents_recovery_until_owner_exits(self):
        run = self.start()
        script = ('import sys; from pathlib import Path; from creator_loom.store import Store; '
                  'from creator_loom.locking import run_lock; '
                  's=Store(Path(sys.argv[1])); '
                  'ctx=run_lock(s,sys.argv[2]); ctx.__enter__(); print("locked",flush=True); '
                  'sys.stdin.read(1); ctx.__exit__(None,None,None)')
        process = subprocess.Popen([sys.executable, "-c", script, str(self.store.root), run],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with self.assertRaisesRegex(ValueError, "lock"):
                self.engine.resume(run)
            self.assertEqual(self.posts, 1)
            process.communicate("x", timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.completed = True
        self.assertEqual(self.engine.resume(run)["status"], "needs_review")

    def test_upstream_artifact_changes_block_resume_without_more_posts(self):
        run = self.start()
        state = self.store.run(run)
        self.engine.artifact(run, state["steps"][0]["result"]).write_text("Changed after submission")
        with self.assertRaises(ValueError):
            self.engine.resume(run)
        self.assertEqual(self.posts, 1)

    def test_upload_uses_generic_filename_and_bypasses_environment_proxies(self):
        path = self.store.root / "private-fixture-name.wav"
        path.write_bytes(wav())
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
            receipt = Client(self.endpoint).upload_voice(path, True)
        self.assertEqual(receipt["asset_id"], "a"*32)
        self.assertNotIn(b"private-fixture-name", self.uploads[0])
        self.assertIn(b'filename="reference.wav"', self.uploads[0])
        with self.assertRaises(ValueError):
            Client(self.endpoint).upload_voice(path, False)
        with self.assertRaises(ValueError):
            Client("https://example.com")

    def test_missing_voice_authorization_excludes_card(self):
        cards = [replace(c, voice_authorized=False) if c.adapter == "mediaflow" else c for c in self.engine.cards]
        with self.assertRaisesRegex(ValueError, "authorization"):
            Engine(self.store, cards).plan(Brief("A podcast", "podcast"))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
    def test_resumed_narration_continues_to_real_video_without_redrafting(self):
        run = self.start("bookcast")
        self.completed = True
        result = self.engine.resume(run)
        self.assertEqual(result["status"], "needs_review")
        film = self.engine.artifact(run, result["steps"][-1]["result"])
        self.assertIn(b"ftyp", film.read_bytes()[:64])
        self.assertEqual(self.writer_calls, 1)
        self.engine.approve(run)


if __name__ == "__main__":
    unittest.main()
