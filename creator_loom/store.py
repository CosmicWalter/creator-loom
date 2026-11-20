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

    def observations(self, profile, capability, model):
        with self.connect() as db:
            return [r[0] for r in db.execute(
                "SELECT rating FROM feedback WHERE profile=? AND capability=? AND model=?",
                (profile, capability, model))]

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
