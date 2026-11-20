"""Reviewed sequential creation with optimistic, artifact-bound continuity."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict

from .domain import Brief, identifier
from .library import Library


class Series:
    def __init__(self, store, engine):
        self.store, self.engine = store, engine
        self.library = Library(store)

    @staticmethod
    def notes(value):
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError("Continuity notes must be at most 4000 characters")
        return value

    def create(self, book_id, brief: Brief, continuity="", start_unit=0):
        if brief.format not in {"article", "novel", "podcast", "bookcast", "talkshow"}:
            raise ValueError("Series requires a text, narration or book-video format")
        book = self.library.book(book_id)
        if type(start_unit) is not int or not 0 <= start_unit < len(book["units"]):
            raise ValueError("start_unit must identify an imported unit")
        self.notes(continuity)
        series_id = uuid.uuid4().hex
        definition = {"book_id": book_id, "start_unit": start_unit, "brief": asdict(brief)}
        with self.store.connect() as db:
            db.execute("INSERT INTO series(id,definition,continuity,cursor) VALUES(?,?,?,?)",
                       (series_id, json.dumps(definition, ensure_ascii=False), continuity, start_unit))
            self.store.event(db, "series_created", series_id, {"book_id": book_id})
        return self.inspect(series_id)

    def inspect(self, series_id):
        identifier(series_id)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM series WHERE id=?", (series_id,)).fetchone()
            if not row:
                raise ValueError("Unknown series")
            result = dict(row)
            result["definition"] = json.loads(result["definition"])
            result["episodes"] = [dict(r) for r in db.execute(
                "SELECT * FROM series_episodes WHERE series_id=? ORDER BY rowid", (series_id,))]
        book = self.library.inspect(result["definition"]["book_id"])
        result["unit_count"] = len(book["units"])
        result["completed"] = result["cursor"] >= result["unit_count"]
        return result

    def _existing(self, run_id, technique):
        if technique is not None and self.store.run(run_id)["plan"]["technique"] != technique:
            raise ValueError("Pending run uses another technique; resolve it before changing the experiment")
        return run_id

    def next(self, series_id, technique=None):
        snapshot = self.inspect(series_id)
        if snapshot["pending_run"]:
            return self._existing(snapshot["pending_run"], technique)
        if snapshot["completed"]:
            raise ValueError("Series has consumed all imported units")
        context = self.library.context(snapshot["definition"]["book_id"], snapshot["cursor"], snapshot["continuity"])
        context["series"] = {"id": series_id, "version": snapshot["version"], "position": snapshot["cursor"]}
        brief = Brief(**snapshot["definition"]["brief"])
        plan = self.engine.plan(brief, technique, context)
        run_id = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM series WHERE id=?", (series_id,)).fetchone()
            if current["pending_run"]:
                return self._existing(current["pending_run"], technique)
            if current["version"] != snapshot["version"] or current["cursor"] != snapshot["cursor"]:
                raise ValueError("Series changed while planning; inspect its current version")
            self.engine.persist(db, run_id, plan)
            db.execute("UPDATE series SET pending_run=? WHERE id=?", (run_id, series_id))
            db.execute("INSERT INTO series_episodes(run_id,series_id,position,state) VALUES(?,?,?,'planned')",
                       (run_id, series_id, snapshot["cursor"]))
            self.store.event(db, "episode_planned", series_id, {"run": run_id, "position": snapshot["cursor"]})
        return run_id

    def accept(self, series_id, run_id, continuity, base_version):
        self.notes(continuity)
        snapshot = self.inspect(series_id)
        if type(base_version) is not int or snapshot["version"] != base_version or snapshot["pending_run"] != run_id:
            raise ValueError("Series version or pending run changed")
        run = self.store.run(run_id)
        if run["status"] != "approved":
            raise ValueError("Approve the actual episode artifacts before advancing the series")
        self.engine.verify_artifacts(run)
        expected = {"id": series_id, "version": base_version, "position": snapshot["cursor"]}
        if run["plan"].get("context", {}).get("series") != expected:
            raise ValueError("Episode does not belong to this series revision")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute('''UPDATE series SET cursor=cursor+1,version=version+1,continuity=?,pending_run=NULL
              WHERE id=? AND version=? AND pending_run=?''', (continuity, series_id, base_version, run_id))
            if changed.rowcount != 1:
                raise ValueError("Series version or pending run changed")
            db.execute("UPDATE series_episodes SET state='accepted',continuity=?,accepted=CURRENT_TIMESTAMP WHERE run_id=?",
                       (continuity, run_id))
            self.store.event(db, "episode_accepted", series_id, {"run": run_id, "version": base_version+1})
        return self.inspect(series_id)

    def reject(self, series_id, run_id, base_version, reason, provider_checked=False):
        if not isinstance(provider_checked, bool):
            raise ValueError("Provider reconciliation must be an explicit boolean declaration")
        if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 2000:
            raise ValueError("Explain rejection in 10–2000 characters")
        snapshot = self.inspect(series_id)
        if type(base_version) is not int or snapshot["version"] != base_version or snapshot["pending_run"] != run_id:
            raise ValueError("Series version or pending run changed")
        run = self.store.run(run_id)
        if run["status"] == "executing":
            raise ValueError("Cannot detach a running episode; reconcile its worker first")
        if any(s["status"] in {"running", "uncertain", "waiting_external"} for s in run["steps"]) and not provider_checked:
            raise ValueError("Unknown remote effects require explicit provider reconciliation (--provider-checked)")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute('''UPDATE series SET version=version+1,pending_run=NULL
              WHERE id=? AND version=? AND pending_run=?
              AND EXISTS(SELECT 1 FROM runs WHERE id=? AND status=?)''',
                                 (series_id, base_version, run_id, run_id, run["status"]))
            if changed.rowcount != 1:
                raise ValueError("Series or execution state changed")
            # Cancel only unexecuted plans. Finished evidence remains immutable.
            db.execute("UPDATE runs SET status='cancelled' WHERE id=? AND status='ready'", (run_id,))
            db.execute("UPDATE series_episodes SET state='rejected',reason=? WHERE run_id=?", (reason, run_id))
            self.store.event(db, "episode_rejected", series_id,
                             {"run": run_id, "provider_checked": provider_checked, "reason": reason})
        return self.inspect(series_id)
