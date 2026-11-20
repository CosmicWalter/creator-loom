"""Feed fixtures exercise research mechanics, not scientific or quality claims."""

import copy
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from unittest.mock import MagicMock

from creator_loom.cli import main
from creator_loom.domain import Brief
from creator_loom.engine import Engine
from creator_loom.feeds import FeedError, canonical_link, discover, feed_url, parse_feed, source_url
from creator_loom.learning import Learning
from creator_loom.research import Research
from creator_loom.routing import load_cards
from creator_loom.store import Store


URL = "https://github.com/Comfy-Org/ComfyUI/releases.atom"
ATOM = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>Video workflow update</title><link rel="self" href="https://example.com/internal-entry"/>
<link rel="alternate" href="https://example.com/release?utm_source=feed#details"/>
<summary type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>Audio and video workflows.</p>
<script>ignore this script</script></div></summary><updated>2026-11-21</updated>
</entry></feed>'''
ENTRY = {"title": "Video workflow update", "source": "https://example.com/release",
         "summary": "Audio and video workflows.", "published": "2026-11-21"}


class FeedTest(unittest.TestCase):
    def test_atom_alternate_link_xhtml_and_canonical_identity(self):
        items = parse_feed(ATOM, URL)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "https://example.com/release")
        self.assertIn("Audio and video", items[0]["summary"])
        self.assertNotIn("ignore this script", items[0]["summary"])
        self.assertFalse(items[0]["trusted_for_execution"])

    def test_rss_html_and_known_http_arxiv_links(self):
        rss = b'<rss version="2.0"><channel><item><title>Paper</title><link>http://arxiv.org/abs/1234.5678</link><description>&lt;p&gt;A model update.&lt;/p&gt;</description></item></channel></rss>'
        item = parse_feed(rss, "https://arxiv.org/rss/cs.AI")[0]
        self.assertEqual(item["source"], "https://arxiv.org/abs/1234.5678")
        self.assertEqual(item["summary"], "A model update.")

    def test_utf16_dtd_invalid_root_and_oversized_body_rejected(self):
        dtd = '<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY x "text">]><feed/>'
        for raw in [dtd.encode("utf-16"), b"<html>not a feed</html>", b"<broken"]:
            with self.assertRaises(FeedError):
                parse_feed(raw, URL)
        with patch("creator_loom.feeds.LIMIT", 10):
            with self.assertRaises(FeedError):
                parse_feed(ATOM, URL)

    def test_private_or_credential_urls_are_not_evidence(self):
        for url in ["https://127.0.0.1/x", "https://localhost/x", "https://host.local/x",
                    "https://example.com:444/x", "https://example.com/?access_token=hidden",
                    "https://example.com/x\nInjected", "http://example.com/x"]:
            with self.assertRaises(ValueError):
                source_url(url)
        with self.assertRaises(ValueError):
            feed_url("https://example.com/feed")
        with self.assertRaises(ValueError):
            feed_url(URL + "?token=hidden")

    def test_transport_failures_are_safe_actionable_errors(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=OSError("private proxy details")):
            with self.assertRaisesRegex(FeedError, "trusted CA") as error:
                discover(URL)
        self.assertNotIn("private proxy", str(error.exception))

    def test_curl_disables_user_config_preserves_tls_and_rejects_redirects(self):
        process = MagicMock()
        process.stdout = io.BytesIO(ATOM + b"\n200")
        process.wait.return_value = 0
        process.poll.return_value = 0
        with patch("creator_loom.feeds.subprocess.Popen", return_value=process) as call:
            self.assertEqual(len(discover(URL, "curl")), 1)
            command = call.call_args.args[0]
            self.assertEqual(command[:2], ["curl", "--disable"])
            self.assertNotIn("--insecure", command)
            self.assertNotIn("-k", command)
            self.assertNotIn("--location", command)
        process.stdout = io.BytesIO(ATOM + b"\n302")
        with patch("creator_loom.feeds.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(FeedError, "redirects"):
                discover(URL, "curl")

    def test_curl_oversized_response_is_bounded_and_process_is_stopped(self):
        process = MagicMock()
        process.stdout = io.BytesIO(b"x" * 100)
        process.poll.return_value = None
        with patch("creator_loom.feeds.subprocess.Popen", return_value=process), patch("creator_loom.feeds.LIMIT", 10):
            with self.assertRaisesRegex(FeedError, "limit"):
                discover(URL, "curl")
        process.kill.assert_called_once()


class ResearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.engine = Engine(self.store, load_cards(None))
        self.learning = Learning(self.store, self.engine)
        self.now = 1000.0
        self.entries = [copy.deepcopy(ENTRY)]
        self.calls = 0
        def fetch(url):
            self.calls += 1
            return copy.deepcopy(self.entries)
        self.research = Research(self.store, self.learning, fetch, lambda: self.now)
        self.research.subscribe("models", URL, ["video", "audio"])

    def tearDown(self):
        self.temp.cleanup()

    def item(self):
        return self.research.inbox("all")[0]

    def test_persistent_deduplication_and_due_intervals(self):
        self.assertEqual(self.research.refresh("models")["new"], 1)
        self.assertEqual(self.research.refresh("models")["unchanged"], 1)
        self.assertEqual(self.research.tick()[0]["outcome"], "not_due")
        self.assertEqual(self.calls, 2)
        restarted = Research(Store(self.store.root), self.learning, self.research.fetcher, lambda: self.now)
        self.assertEqual(len(restarted.inbox()), 1)
        self.assertEqual(restarted.sources()[0]["id"], "models")

    def test_canonical_deduplication_across_sources_and_old_observations(self):
        self.research.refresh("models")
        self.entries[0]["summary"] = "New video and audio information."
        self.research.refresh("models")
        self.research.subscribe("papers", "https://arxiv.org/rss/cs.AI", ["video"])
        self.entries = [copy.deepcopy(ENTRY)]
        report = self.research.refresh("papers")
        self.assertEqual(report["unchanged"], 1)
        item = self.research.inspect(self.item()["id"])
        self.assertEqual(item["revision"], 2)
        self.assertEqual(item["subscriptions"], ["models", "papers"])
        self.assertIn("New video", item["payload"]["summary"])

    def test_relevance_has_visible_literal_evidence_and_can_be_reconfigured(self):
        self.research.refresh("models")
        item = self.item()
        self.assertEqual(item["relevance"], 1)
        self.assertEqual(item["matched_keywords"], ["audio", "video"])
        self.research.configure("models", 1, True, ["unrelated"])
        self.assertEqual(self.item()["relevance"], 0)
        with self.assertRaisesRegex(ValueError, "version"):
            self.research.configure("models", 1, False)

    def test_failed_fetch_retains_evidence_and_does_not_persist_error_body(self):
        self.research.refresh("models")
        self.research.fetcher = lambda _: (_ for _ in ()).throw(ValueError("private-secret-response"))
        report = self.research.refresh("models")
        self.assertEqual(report["outcome"], "failed")
        self.assertEqual(len(self.research.inbox()), 1)
        self.assertNotIn("private-secret-response", (self.store.root / "loom.sqlite3").read_bytes().decode(errors="replace"))
        self.assertEqual(self.research.sources()[0]["last_error"], "ValueError")

    def test_invalid_batch_is_atomic_and_does_not_erase_previous_items(self):
        self.entries.append({"title": 123, "source": "https://example.com/invalid"})
        self.assertEqual(self.research.refresh("models")["outcome"], "failed")
        self.assertEqual(self.research.inbox(), [])

    def test_source_failure_does_not_block_other_subscriptions(self):
        self.research.subscribe("papers", "https://arxiv.org/rss/cs.AI", ["video"])
        def fetch(url):
            if url == URL:
                raise FeedError("One source is unavailable")
            return [ENTRY]
        self.research.fetcher = fetch
        reports = self.research.tick()
        self.assertEqual([r["outcome"] for r in reports], ["failed", "succeeded"])
        self.assertEqual(len(self.research.inbox()), 1)

    def test_concurrent_refresh_claims_only_one_network_request(self):
        entered, release = threading.Event(), threading.Event()
        def fetch(url):
            entered.set()
            self.assertTrue(release.wait(3))
            return [ENTRY]
        self.research.fetcher = fetch
        with ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(self.research.refresh, "models")
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.research.refresh("models")["outcome"], "busy")
            release.set()
            self.assertEqual(future.result()["new"], 1)

    def test_configuration_change_supersedes_inflight_observation(self):
        def fetch(url):
            self.research.configure("models", 1, False)
            return [ENTRY]
        self.research.fetcher = fetch
        self.assertEqual(self.research.refresh("models")["outcome"], "superseded")
        self.assertEqual(self.research.inbox(), [])
        self.assertEqual(self.research.refresh("models")["outcome"], "disabled")

    def test_expired_lease_cannot_overwrite_a_newer_worker_result(self):
        updated = {**ENTRY, "summary": "New worker's observation."}
        second = Research(self.store, self.learning, lambda _: [updated], lambda: self.now)
        def fetch(url):
            self.now += 200
            self.assertEqual(second.refresh("models")["outcome"], "succeeded")
            return [ENTRY]
        self.research.fetcher = fetch
        self.assertEqual(self.research.refresh("models")["outcome"], "superseded")
        self.assertEqual(self.item()["payload"]["summary"], updated["summary"])

    def test_dismissal_is_preserved_and_stale_reviews_are_visible(self):
        self.research.refresh("models")
        item = self.item()
        self.research.review(item["id"], 1, "Not relevant to our current creative work.")
        self.entries[0]["summary"] = "A revised model capability description."
        self.research.refresh("models")
        self.assertEqual(self.research.inbox(), [])
        changed = self.research.inbox("changed")[0]
        self.assertEqual(changed["state"], "dismissed")
        with self.assertRaisesRegex(ValueError, "revision"):
            self.research.review(item["id"], 1, "This review used an obsolete evidence version.")
        self.research.review(item["id"], 2, "Reopen the materially changed description.", reopen=True)
        self.assertEqual(len(self.research.inbox()), 1)

    def test_reviewed_proposal_freezes_evidence_and_still_requires_evaluation(self):
        self.research.refresh("models")
        item = self.item()
        self.research.review(item["id"], 1, "A human reviewed this synthetic source fixture.", "concrete", "Use concrete details.")
        with self.assertRaises(ValueError):
            self.learning.promote("concrete")
        self.entries[0]["summary"] = "A later revision must not rewrite experiment provenance."
        self.research.refresh("models")
        with self.store.connect() as db:
            proposal = json.loads(db.execute("SELECT payload FROM techniques WHERE id='concrete'").fetchone()[0])
        self.assertEqual(proposal["origin"]["revision"], 1)
        self.assertEqual(proposal["origin"]["snapshot"]["summary"], ENTRY["summary"])
        self.assertTrue(self.research.inbox("changed")[0]["review_stale"])
        pairs = []
        for i in range(3):
            brief = Brief(f"Original fixture {i}", "cover", local_only=True)
            baseline = self.engine.create(brief)
            candidate = self.engine.create(brief, "concrete")
            for run in [baseline, candidate]:
                self.engine.execute(run)
                self.engine.approve(run)
            pairs.append({"baseline": baseline, "candidate": candidate, "baseline_score": 0.5,
                          "candidate_score": 0.7, "rationale": "Synthetic review scores test the gate, not creative improvement."})
        self.assertTrue(self.learning.evaluate("concrete", pairs)["passed"])
        self.learning.promote("concrete")
        self.assertEqual(self.engine.plan(Brief("Future", "cover"))["technique"], "concrete")
        self.learning.rollback("concrete")

    def test_proposal_and_review_are_atomic_on_invalid_guidance(self):
        self.research.refresh("models")
        item = self.item()
        with self.assertRaises(ValueError):
            self.research.review(item["id"], 1, "A review explanation for the synthetic fixture.", "invalid", "")
        self.assertEqual(self.item()["state"], "inbox")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM techniques").fetchone()[0], 0)

    def test_cli_worker_once_has_no_implicit_background_process(self):
        self.research.configure("models", 1, False)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--data", str(self.store.root), "research-worker"]), 0)
        self.assertEqual(json.loads(output.getvalue()), [])

    def test_subscription_schema_upgrade_retains_existing_source(self):
        legacy = self.store.root / "legacy"
        legacy.mkdir()
        with closing(sqlite3.connect(legacy / "loom.sqlite3")) as db, db:
            db.execute('''CREATE TABLE subscriptions(id TEXT PRIMARY KEY,url TEXT UNIQUE NOT NULL,
              keywords TEXT NOT NULL,enabled INTEGER DEFAULT 1,version INTEGER DEFAULT 1,
              interval_seconds INTEGER,next_check REAL DEFAULT 0,last_checked REAL,last_error TEXT,
              lease_token TEXT,lease_until REAL)''')
            db.execute("INSERT INTO subscriptions(id,url,keywords,interval_seconds) VALUES(?,?,?,?)", ("existing", URL, "[]", 21600))
        upgraded = Store(legacy)
        source = Research(upgraded, self.learning).sources()[0]
        self.assertEqual(source["id"], "existing")
        self.assertEqual(source["transport"], "urllib")
