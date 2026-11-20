"""Persistent research subscriptions and explicitly reviewed technique proposals."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid

from .domain import identifier
from .feeds import canonical_link, discover, feed_url


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def relevance(payload, keywords):
    text = (payload["title"] + " " + payload["summary"]).casefold()
    matches = []
    for keyword in keywords:
        word = keyword.casefold()
        found = bool(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text)) if word.isascii() else word in text
        if found:
            matches.append(keyword)
    return {"score": len(matches)/len(keywords) if keywords else 0.0,
            "matches": matches, "method": "literal title/summary keyword matching"}


class Research:
    def __init__(self, store, learning, fetcher=None, clock=None):
        self.store, self.learning = store, learning
        self.fetcher = fetcher
        self.clock = clock or time.time

    @staticmethod
    def settings(keywords, interval):
        if (not isinstance(keywords, list) or len(keywords) > 30 or
                any(not isinstance(k, str) or not 1 <= len(k.strip()) <= 80 for k in keywords)):
            raise ValueError("Provide at most 30 nonempty keywords of at most 80 characters")
        if type(interval) is not int or not 300 <= interval <= 604800:
            raise ValueError("Source refresh interval must be 300–604800 seconds")
        return list(dict.fromkeys(k.strip().casefold() for k in keywords))

    def subscribe(self, name, url, keywords, interval=21600, transport="urllib"):
        identifier(name)
        feed_url(url)
        keywords = self.settings(keywords, interval)
        if transport not in {"urllib", "curl"}:
            raise ValueError("Feed transport must be urllib or curl")
        with self.store.connect() as db:
            db.execute("INSERT INTO subscriptions(id,url,keywords,interval_seconds,transport) VALUES(?,?,?,?,?)",
                       (name, url, json.dumps(keywords), interval, transport))
            self.store.event(db, "source_subscribed", name, {"url": url, "keywords": keywords})
        return self.sources()

    def sources(self):
        with self.store.connect() as db:
            return [{**dict(r), "keywords": json.loads(r["keywords"])}
                    for r in db.execute("SELECT id,url,keywords,transport,enabled,version,interval_seconds,next_check,last_checked,last_error FROM subscriptions ORDER BY id")]

    def configure(self, name, version, enabled, keywords=None, interval=None, transport=None):
        identifier(name)
        if type(enabled) is not bool or type(version) is not int:
            raise ValueError("Source updates require a version and explicit enabled boolean")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM subscriptions WHERE id=?", (name,)).fetchone()
            if not row or row["version"] != version:
                raise ValueError("Source version changed or source is missing")
            words = json.loads(row["keywords"]) if keywords is None else keywords
            seconds = row["interval_seconds"] if interval is None else interval
            words = self.settings(words, seconds)
            selected_transport = row["transport"] if transport is None else transport
            if selected_transport not in {"urllib", "curl"}:
                raise ValueError("Feed transport must be urllib or curl")
            db.execute("UPDATE subscriptions SET keywords=?,enabled=?,interval_seconds=?,transport=?,version=version+1,next_check=0 WHERE id=?",
                       (json.dumps(words), int(enabled), seconds, selected_transport, name))
            # Relevance is a view of current operator interests, not a change to evidence.
            for sighting in db.execute("SELECT s.item_id,i.payload FROM research_sightings s JOIN research_items i ON i.id=s.item_id WHERE s.subscription_id=?", (name,)).fetchall():
                db.execute("UPDATE research_sightings SET relevance=? WHERE subscription_id=? AND item_id=?",
                           (json.dumps(relevance(json.loads(sighting["payload"]), words)), name, sighting["item_id"]))
            self.store.event(db, "source_configured", name, {"version": version+1, "enabled": enabled})
        return self.sources()

    @staticmethod
    def normalized(entry):
        if not isinstance(entry, dict):
            raise ValueError("Invalid feed entry")
        payload = {k: entry.get(k, "") for k in ["title", "source", "summary", "published"]}
        if any(not isinstance(v, str) for v in payload.values()) or not payload["title"].strip():
            raise ValueError("Invalid feed entry text")
        payload["source"] = canonical_link(payload["source"], payload["source"])
        payload["title"] = payload["title"][:500]
        payload["summary"] = payload["summary"][:6000]
        payload["published"] = payload["published"][:100]
        return payload

    def refresh(self, name, due_only=False):
        identifier(name)
        now, token = self.clock(), uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM subscriptions WHERE id=?", (name,)).fetchone()
            if not row:
                raise ValueError("Unknown source")
            if not row["enabled"]:
                return {"source": name, "outcome": "disabled"}
            if row["lease_until"] is not None and row["lease_until"] > now:
                return {"source": name, "outcome": "busy"}
            if due_only and row["next_check"] > now:
                return {"source": name, "outcome": "not_due"}
            snapshot = dict(row)
            db.execute("UPDATE subscriptions SET lease_token=?,lease_until=? WHERE id=?", (token, now+120, name))
        error = None
        try:
            entries = self.fetcher(snapshot["url"]) if self.fetcher else discover(snapshot["url"], snapshot["transport"])
            if not isinstance(entries, list) or len(entries) > 200:
                raise ValueError("Invalid feed batch")
            # Normalize the complete batch before opening a write transaction:
            # a malformed entry cannot leave a partially applied observation.
            batch = {}
            for entry in entries:
                item = self.normalized(entry)
                batch.setdefault(item["source"], item)
        except (ValueError, OSError) as exc:
            error = type(exc).__name__
            batch = {}
        report = {"source": name, "outcome": "failed" if error else "succeeded",
                  "new": 0, "updated": 0, "unchanged": 0, "error_type": error}
        checked = self.clock()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM subscriptions WHERE id=?", (name,)).fetchone()
            if current["lease_token"] != token or current["version"] != snapshot["version"]:
                report["outcome"] = "superseded"
                db.execute("UPDATE subscriptions SET lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=?", (name, token))
            else:
                if not error:
                    keywords = json.loads(snapshot["keywords"])
                    for payload in batch.values():
                        item_id = hashlib.sha256(payload["source"].encode()).hexdigest()
                        digest = fingerprint(payload)
                        previous = db.execute("SELECT * FROM research_items WHERE id=?", (item_id,)).fetchone()
                        revision = previous["revision"] if previous else 0
                        known = db.execute("SELECT 1 FROM research_revisions WHERE item_id=? AND sha256=?", (item_id, digest)).fetchone()
                        changed = previous is None or (previous["sha256"] != digest and not known)
                        if changed:
                            revision += 1
                            if previous is None:
                                db.execute("INSERT INTO research_items(id,source,payload,sha256,revision) VALUES(?,?,?,?,?)",
                                           (item_id, payload["source"], json.dumps(payload, ensure_ascii=False), digest, revision))
                                report["new"] += 1
                            else:
                                db.execute("UPDATE research_items SET payload=?,sha256=?,revision=? WHERE id=?",
                                           (json.dumps(payload, ensure_ascii=False), digest, revision, item_id))
                                report["updated"] += 1
                            db.execute("INSERT INTO research_revisions VALUES(?,?,?,?,?)",
                                       (item_id, revision, json.dumps(payload, ensure_ascii=False), digest, checked))
                        else:
                            report["unchanged"] += 1
                        db.execute('''INSERT INTO research_sightings VALUES(?,?,?,?,?)
                          ON CONFLICT(subscription_id,item_id) DO UPDATE SET relevance=excluded.relevance,last_seen=excluded.last_seen''',
                                   (name, item_id, json.dumps(relevance(payload, keywords)), checked, checked))
                delay = min(snapshot["interval_seconds"], 900) if error else snapshot["interval_seconds"]
                db.execute("UPDATE subscriptions SET last_checked=?,last_error=?,next_check=?,lease_token=NULL,lease_until=NULL WHERE id=?",
                           (checked, error, checked+delay, name))
            db.execute("INSERT INTO feed_runs VALUES(?,?,?,?,?)", (uuid.uuid4().hex, name, report["outcome"], json.dumps(report), checked))
        return report

    def tick(self):
        return [self.refresh(source["id"], due_only=True) for source in self.sources() if source["enabled"]]

    def inbox(self, state="inbox"):
        if state not in {"inbox", "dismissed", "proposed", "changed", "all"}:
            raise ValueError("Unknown inbox filter")
        with self.store.connect() as db:
            items = []
            for row in db.execute("SELECT * FROM research_items"):
                item = {**dict(row), "payload": json.loads(row["payload"])}
                item["review_stale"] = item["decision_revision"] is not None and item["decision_revision"] != item["revision"]
                if state != "all" and not (item["review_stale"] if state == "changed" else item["state"] == state):
                    continue
                sightings = [json.loads(s[0]) for s in db.execute("SELECT relevance FROM research_sightings WHERE item_id=?", (item["id"],))]
                item["relevance"] = max((s["score"] for s in sightings), default=0)
                item["matched_keywords"] = sorted({word for s in sightings for word in s["matches"]})
                item["trusted_for_execution"] = False
                items.append(item)
        return sorted(items, key=lambda x: (-x["relevance"], x["payload"]["source"]))

    def inspect(self, item_id):
        identifier(item_id)
        item = next((i for i in self.inbox("all") if i["id"] == item_id), None)
        if item is None:
            raise ValueError("Unknown research item")
        with self.store.connect() as db:
            item["revisions"] = [{**dict(r), "payload": json.loads(r["payload"])} for r in db.execute(
                "SELECT * FROM research_revisions WHERE item_id=? ORDER BY revision", (item_id,))]
            item["subscriptions"] = [r[0] for r in db.execute("SELECT subscription_id FROM research_sightings WHERE item_id=? ORDER BY subscription_id", (item_id,))]
        return item

    def review(self, item_id, revision, note, technique=None, guidance=None, reopen=False):
        identifier(item_id)
        if type(revision) is not int or not isinstance(note, str) or not 10 <= len(note.strip()) <= 2000:
            raise ValueError("Review requires an integer revision and a 10–2000 character explanation")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            item = db.execute("SELECT * FROM research_items WHERE id=?", (item_id,)).fetchone()
            if not item or item["revision"] != revision:
                raise ValueError("Research revision changed; inspect the current evidence")
            if technique:
                if item["state"] == "dismissed":
                    raise ValueError("Reopen dismissed evidence before proposing a technique")
                payload = json.loads(item["payload"])
                origin = {"kind": "reviewed_feed", "item": item_id, "revision": revision,
                          "sha256": item["sha256"], "snapshot": payload, "review_note": note}
                self.learning.propose_in(db, technique, payload["source"], guidance, origin)
                state = "proposed"
            else:
                state = "inbox" if reopen else "dismissed"
            db.execute("UPDATE research_items SET state=?,decision_revision=?,review_note=?,proposal_id=? WHERE id=?",
                       (state, revision, note, technique, item_id))
            self.store.event(db, "research_reviewed", item_id, {"revision": revision, "state": state, "technique": technique})
        return self.inspect(item_id)
