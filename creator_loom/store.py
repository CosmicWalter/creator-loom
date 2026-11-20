from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    """Single-user durable state. SQLite transactions serialize claims and feedback."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, brief TEXT NOT NULL, plan TEXT NOT NULL,
                  status TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS steps (
                  run_id TEXT, id TEXT, status TEXT NOT NULL, result TEXT,
                  PRIMARY KEY(run_id,id));
                CREATE TABLE IF NOT EXISTS profiles (
                  id TEXT PRIMARY KEY, preferences TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS feedback (
                  run_id TEXT, step_id TEXT, profile TEXT NOT NULL,
                  capability TEXT NOT NULL, model TEXT NOT NULL, rating REAL NOT NULL,
                  PRIMARY KEY(run_id,step_id));
                CREATE TABLE IF NOT EXISTS techniques (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
                  evaluation TEXT, previous_state TEXT);
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL,
                  payload TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS practice (
                  id TEXT PRIMARY KEY, profile TEXT NOT NULL, run_id TEXT NOT NULL,
                  step_id TEXT NOT NULL, dimension TEXT NOT NULL,
                  before_score REAL NOT NULL, after_score REAL NOT NULL,
                  rationale TEXT NOT NULL, artifact TEXT NOT NULL,
                  created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS measurements (
                  run_id TEXT NOT NULL, step_id TEXT NOT NULL, profile TEXT NOT NULL,
                  task TEXT NOT NULL, model TEXT NOT NULL, signature TEXT NOT NULL,
                  outcome TEXT NOT NULL, elapsed_seconds REAL NOT NULL,
                  usage TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY(run_id,step_id));
                CREATE INDEX IF NOT EXISTS measurements_scope ON measurements(profile,task,signature);
                CREATE INDEX IF NOT EXISTS feedback_scope ON feedback(profile,capability,model);
                CREATE TABLE IF NOT EXISTS books (
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, format TEXT NOT NULL,
                  source_sha256 TEXT NOT NULL, rights TEXT NOT NULL, rights_note TEXT NOT NULL,
                  units TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS series (
                  id TEXT PRIMARY KEY, definition TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
                  version INTEGER NOT NULL DEFAULT 1, continuity TEXT NOT NULL DEFAULT '',
                  pending_run TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS series_episodes (
                  run_id TEXT PRIMARY KEY, series_id TEXT NOT NULL, position INTEGER NOT NULL,
                  state TEXT NOT NULL, continuity TEXT, reason TEXT,
                  created TEXT DEFAULT CURRENT_TIMESTAMP, accepted TEXT);
                CREATE INDEX IF NOT EXISTS episodes_series ON series_episodes(series_id,position);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "loom.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def event(db, kind, subject, payload):
        db.execute("INSERT INTO events(kind,subject,payload) VALUES(?,?,?)",
                   (kind, subject, json.dumps(payload, ensure_ascii=False)))

    def preferences(self, profile):
        with self.connect() as db:
            row = db.execute("SELECT preferences FROM profiles WHERE id=?", (profile,)).fetchone()
            return json.loads(row[0]) if row else {}

    def set_preferences(self, profile, values):
        with self.connect() as db:
            db.execute("INSERT INTO profiles VALUES(?,?) ON CONFLICT(id) DO UPDATE SET preferences=excluded.preferences",
                       (profile, json.dumps(values, ensure_ascii=False)))

    def observations(self, profile, capability, model, task=None, signature=None):
        with self.connect() as db:
            rows = db.execute('''SELECT f.rating,f.step_id,r.brief,r.plan FROM feedback f
              JOIN runs r ON r.id=f.run_id WHERE f.profile=? AND f.capability=? AND f.model=?''',
                              (profile, capability, model)).fetchall()
        from .domain import ModelCard
        ratings = []
        for row in rows:
            if task is not None and task != f"{json.loads(row['brief'])['format']}:{row['step_id']}":
                continue
            if signature is not None:
                spec = next(s for s in json.loads(row["plan"])["steps"] if s["id"] == row["step_id"])
                if ModelCard(**spec["model"]).signature() != signature:
                    continue
            ratings.append(row["rating"])
        return ratings

    def performance(self, profile, task, signature):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT outcome,elapsed_seconds FROM measurements WHERE profile=? AND task=? AND signature=?",
                (profile, task, signature))]

    @staticmethod
    def measurement(db, run_id, step_id, profile, task, card, outcome, elapsed, usage):
        db.execute('''INSERT INTO measurements(run_id,step_id,profile,task,model,signature,
          outcome,elapsed_seconds,usage) VALUES(?,?,?,?,?,?,?,?,?)''',
                   (run_id, step_id, profile, task, card.id, card.signature(), outcome, elapsed, json.dumps(usage)))

    def metrics(self, profile, run_id=None):
        from .domain import identifier
        identifier(profile)
        with self.connect() as db:
            sql = "SELECT run_id,step_id,task,model,outcome,elapsed_seconds,usage FROM measurements WHERE profile=?"
            args = [profile]
            if run_id:
                identifier(run_id)
                sql += " AND run_id=?"
                args.append(run_id)
            rows = [{**dict(r), "usage": json.loads(r["usage"])} for r in db.execute(sql, args)]
        priced = [r["usage"]["token_cost_estimate"] for r in rows if r["usage"].get("token_cost_estimate") is not None]
        return {"profile": profile, "steps": rows, "priced_steps": len(priced),
                "unpriced_steps": len(rows)-len(priced), "known_token_cost_estimate": sum(priced),
                "billing": "Configured token rates only; not provider invoices or complete spending"}

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("Unknown run")
            value = dict(row)
            value["brief"] = json.loads(value["brief"])
            value["plan"] = json.loads(value["plan"])
            value["steps"] = [{**dict(r), "result": json.loads(r["result"]) if r["result"] else None}
                              for r in db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY rowid", (run_id,))]
            return value

    def feedback(self, run_id, step_id, rating):
        from .domain import bounded
        bounded(rating, 0, 1, "rating")
        run = self.run(run_id)
        step = next((s for s in run["steps"] if s["id"] == step_id), None)
        if not step or step["status"] != "done":
            raise ValueError("Feedback requires a completed step")
        spec = next(s for s in run["plan"]["steps"] if s["id"] == step_id)
        with self.connect() as db:
            db.execute('''INSERT INTO feedback VALUES(?,?,?,?,?,?)
              ON CONFLICT(run_id,step_id) DO UPDATE SET rating=excluded.rating''',
                       (run_id, step_id, run["brief"]["profile"], spec["capability"], spec["model"]["id"], rating))
            self.event(db, "feedback", run_id, {"step": step_id, "rating": rating})

    def forget(self, profile):
        with self.connect() as db:
            db.execute("DELETE FROM profiles WHERE id=?", (profile,))
            db.execute("DELETE FROM feedback WHERE profile=?", (profile,))
            db.execute("DELETE FROM measurements WHERE profile=?", (profile,))
