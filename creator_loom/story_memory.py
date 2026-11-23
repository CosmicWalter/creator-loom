"""Versioned human-reviewed character facts with exact source/episode citations."""

from __future__ import annotations

import json

from .domain import identifier
from .evidence import digest
from .library import Library


class StoryMemory:
    def __init__(self, store):
        self.store, self.library = store, Library(store)

    def series(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM series WHERE id=?", (name,)).fetchone()
        if not row:
            raise ValueError("Unknown series")
        return {**dict(row), "definition": json.loads(row["definition"])}

    def snapshot(self, name, version=None):
        series = self.series(name)
        version = series["memory_version"] if version is None else version
        if type(version) is not int or version < 0:
            raise ValueError("Memory version must be a nonnegative integer")
        if version == 0:
            return {"series": name, "version": 0, "sha256": digest({"characters": []}), "payload": {"characters": []}}
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM story_memories WHERE series_id=? AND version=?", (name, version)).fetchone()
        if not row:
            raise ValueError("Unknown character-memory version")
        result = {"series": name, "version": version, "sha256": row["sha256"], "payload": json.loads(row["payload"])}
        self.validate(result)
        return result

    def inspect(self, name, version=None):
        series = self.series(name)
        result = self.snapshot(name, version)
        with self.store.connect() as db:
            history = [dict(r) for r in db.execute("SELECT version,review_note,created FROM story_memories WHERE series_id=? ORDER BY version DESC", (name,))]
        return {"snapshot": result, "history": history, "series_version": series["version"], "current_version": series["memory_version"], "pending_run": series["pending_run"], "cursor": series["cursor"]}

    def citation(self, series, citation, enforce_position=False):
        if not isinstance(citation, dict) or citation.get("kind") not in {"source", "episode"}:
            raise ValueError("A character fact needs a source-unit or accepted-episode citation")
        kind = citation["kind"]
        allowed = {"kind", "unit", "quote", "sha256"} if kind == "source" else {"kind", "run", "step", "quote", "sha256"}
        required = allowed-{"sha256"}
        if not required <= set(citation) or set(citation)-allowed:
            raise ValueError("Unexpected character fact citation fields")
        quote = citation["quote"]
        if not isinstance(quote, str) or not 5 <= len(quote.strip()) <= 400:
            raise ValueError("Fact citation needs an exact 5–400 character quotation")
        if kind == "source":
            unit = citation["unit"]
            if type(unit) is not int or unit < 0 or enforce_position and unit > series["cursor"]:
                raise ValueError("Fact evidence cannot cite an unvisited future source unit")
            source = self.library.context(series["definition"]["book_id"], unit)["source"]
            text, checksum = source["text"], source["sha256"]
        else:
            identifier(citation["run"]); identifier(citation["step"])
            with self.store.connect() as db:
                episode = db.execute("SELECT * FROM series_episodes WHERE run_id=? AND series_id=? AND state='accepted'", (citation["run"], series["id"])).fetchone()
            if not episode or enforce_position and episode["position"] >= series["cursor"]:
                raise ValueError("Fact evidence must cite an accepted episode in this series")
            from .engine import Engine
            run = self.store.run(citation["run"])
            if run["status"] != "approved":
                raise ValueError("Cited episode is no longer approved")
            spec = next((s for s in run["plan"]["steps"] if s["id"] == citation["step"]), None)
            step = next((s for s in run["steps"] if s["id"] == citation["step"]), None)
            if not spec or spec["capability"] != "text" or not step or not step["result"]:
                raise ValueError("Episode evidence must refer to its actual text output")
            path = Engine(self.store, []).artifact(run["id"], step["result"])
            text, checksum = path.read_text(encoding="utf-8"), step["result"]["sha256"]
        if quote not in text or citation.get("sha256", checksum) != checksum:
            raise ValueError("Fact quotation is not present in the bound evidence")
        return {**citation, "sha256": checksum}

    def normalize(self, series, payload):
        if not isinstance(payload, dict) or set(payload) != {"characters"} or not isinstance(payload["characters"], list) or len(payload["characters"]) > 30:
            raise ValueError("Memory needs at most 30 character records")
        seen, total, characters = set(), 0, []
        for character in payload["characters"]:
            if not isinstance(character, dict) or set(character) != {"id", "name", "facts"}:
                raise ValueError("Character record needs id, display name and facts")
            identifier(character["id"])
            if character["id"] in seen or not isinstance(character["name"], str) or not 1 <= len(character["name"].strip()) <= 100:
                raise ValueError("Character IDs must be distinct and names bounded")
            seen.add(character["id"])
            if not isinstance(character["facts"], list) or not 1 <= len(character["facts"]) <= 20:
                raise ValueError("A character needs 1–20 reviewed facts")
            fact_ids, facts = set(), []
            for fact in character["facts"]:
                if not isinstance(fact, dict) or set(fact) != {"id", "kind", "text", "citation"}:
                    raise ValueError("Fact needs id, kind, text and evidence citation")
                identifier(fact["id"])
                if fact["id"] in fact_ids or fact["kind"] not in {"identity", "appearance", "relationship", "state", "constraint"} or not isinstance(fact["text"], str) or not 1 <= len(fact["text"].strip()) <= 500:
                    raise ValueError("Fact IDs, categories and text must be valid")
                fact_ids.add(fact["id"]); total += 1
                facts.append({"id": fact["id"], "kind": fact["kind"], "text": fact["text"].strip(), "citation": self.citation(series, fact["citation"], enforce_position=True)})
            characters.append({"id": character["id"], "name": character["name"].strip(), "facts": facts})
        normalized = {"characters": characters}
        if total > 60 or len(json.dumps(normalized, ensure_ascii=False)) > 20000:
            raise ValueError("Character memory exceeds 60 facts or 20000 serialized characters")
        return normalized

    def update(self, name, payload, series_version, memory_version, review_note, reviewed):
        if reviewed is not True or not isinstance(review_note, str) or not 10 <= len(review_note.strip()) <= 2000:
            raise ValueError("Explicit character-memory review and a 10–2000 character explanation are required")
        series = self.series(name)
        if type(series_version) is not int or type(memory_version) is not int or series["version"] != series_version or series["memory_version"] != memory_version or series["pending_run"]:
            raise ValueError("Series/memory changed or an episode is pending; finish it before editing memory")
        normalized = self.normalize(series, payload)
        checksum = digest(normalized)
        if checksum == self.snapshot(name)["sha256"]:
            raise ValueError("Memory revision must change the reviewed character facts")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.update_in(db, name, normalized, series_version, memory_version, review_note)
        return self.inspect(name)

    def update_in(self, db, name, normalized, series_version, memory_version, review_note):
        """Commit reviewed facts with another local review decision atomically."""
        checksum = digest(normalized)
        changed = db.execute("UPDATE series SET memory_version=memory_version+1,version=version+1 WHERE id=? AND version=? AND memory_version=? AND pending_run IS NULL", (name, series_version, memory_version))
        if changed.rowcount != 1:
            raise ValueError("Series changed during character-memory review")
        # No content is published or inferred: each revision is a reviewed local snapshot.
        db.execute("INSERT INTO story_memories(series_id,version,payload,sha256,review_note) VALUES(?,?,?,?,?)", (name, memory_version+1, json.dumps(normalized, ensure_ascii=False), checksum, review_note))
        self.store.event(db, "character_memory_reviewed", name, {"memory_version": memory_version+1, "series_version": series_version+1, "sha256": checksum})

    def validate(self, snapshot):
        if not isinstance(snapshot, dict) or set(snapshot) != {"series", "version", "sha256", "payload"}:
            raise ValueError("Invalid character-memory snapshot")
        series = self.series(snapshot["series"])
        if type(snapshot["version"]) is not int or snapshot["version"] < 0 or digest(snapshot["payload"]) != snapshot["sha256"]:
            raise ValueError("Character-memory snapshot changed")
        if snapshot["version"] == 0:
            if snapshot["payload"] != {"characters": []}:
                raise ValueError("Initial memory must be empty")
            return
        with self.store.connect() as db:
            row = db.execute("SELECT payload,sha256 FROM story_memories WHERE series_id=? AND version=?", (snapshot["series"], snapshot["version"])).fetchone()
        if not row or row["sha256"] != snapshot["sha256"] or json.loads(row["payload"]) != snapshot["payload"]:
            raise ValueError("Character-memory provenance is missing or changed")
        for character in snapshot["payload"]["characters"]:
            for fact in character["facts"]:
                self.citation(series, fact["citation"])

    @staticmethod
    def prompt_data(snapshot):
        return {"characters": [{"name": c["name"], "facts": [{"kind": f["kind"], "text": f["text"]} for f in c["facts"]]} for c in snapshot["payload"]["characters"]]}

    def evidence_options(self, name):
        series = self.series(name)
        book = self.library.inspect(series["definition"]["book_id"])
        sources = [{"kind": "source", "unit": u["index"], "title": u["title"]} for u in book["units"] if u["index"] <= series["cursor"]]
        with self.store.connect() as db:
            accepted = db.execute("SELECT run_id,position FROM series_episodes WHERE series_id=? AND state='accepted' ORDER BY rowid", (name,)).fetchall()
        for episode in accepted:
            run = self.store.run(episode["run_id"])
            sources.extend({"kind": "episode", "run": run["id"], "step": s["id"], "title": f"Accepted episode {episode['position']+1} · {s['id']}"} for s in run["plan"]["steps"] if s["capability"] == "text")
        return sources

    def evidence_text(self, name, ref):
        series = self.series(name)
        if not isinstance(ref, dict) or set(ref) not in [{"kind", "unit"}, {"kind", "run", "step"}]:
            raise ValueError("Select a source unit or accepted episode")
        if ref not in [{k: v for k, v in option.items() if k != "title"} for option in self.evidence_options(name)]:
            raise ValueError("Evidence is outside the available series history")
        if ref["kind"] == "source":
            return self.library.context(series["definition"]["book_id"], ref["unit"])["source"]["text"]
        from .engine import Engine
        run = self.store.run(ref["run"])
        if run["status"] != "approved":
            raise ValueError("Evidence episode is no longer approved")
        step = next(s for s in run["steps"] if s["id"] == ref["step"])
        return Engine(self.store, []).artifact(run["id"], step["result"]).read_text(encoding="utf-8")
