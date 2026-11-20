from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from .domain import bounded, identifier
from . import __version__


def source_url(url):
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment:
        raise ValueError("Evidence requires a public HTTPS source without credentials or fragments")
    return url


def discover(url):
    """Explicitly fetched public release feeds; fetched text is never executable."""
    from .adapters import NoRedirect
    source_url(url)
    if urlsplit(url).hostname not in {"github.com", "huggingface.co", "arxiv.org", "export.arxiv.org"}:
        raise ValueError("Discovery supports GitHub, Hugging Face and arXiv feeds only")
    request = urllib.request.Request(url, headers={"User-Agent": f"creator-loom/{__version__}"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024 or b"<!DOCTYPE" in raw.upper():
        raise ValueError("Feed is oversized or contains a document type declaration")
    root = ET.fromstring(raw)
    entries = list(root.findall("{http://www.w3.org/2005/Atom}entry")) + list(root.findall(".//item"))
    results = []
    for entry in entries[:20]:
        def field(name):
            return entry.find(name) if entry.find(name) is not None else entry.find("{http://www.w3.org/2005/Atom}" + name)
        title, link = field("title"), field("link")
        if title is None or link is None:
            continue
        href = link.get("href") or link.text or ""
        try:
            source_url(href)
        except ValueError:
            continue
        results.append({"title": "".join(title.itertext())[:500], "source": href,
                        "state": "discovered", "trusted_for_execution": False})
    return results


class Learning:
    def __init__(self, store, engine):
        self.store, self.engine = store, engine

    def propose(self, name, source, guidance):
        identifier(name)
        source_url(source)
        if not isinstance(guidance, str) or not 1 <= len(guidance.strip()) <= 2000:
            raise ValueError("Guidance must contain 1–2000 characters")
        with self.store.connect() as db:
            active = db.execute("SELECT id,payload FROM techniques WHERE state='active'").fetchone()
            payload = {"source": source, "guidance": guidance,
                       "baseline": active["id"] if active else None,
                       "baseline_snapshot": json.loads(active["payload"]) if active else None}
            db.execute("INSERT INTO techniques(id,payload,state) VALUES(?,?,'proposed')", (name, json.dumps(payload)))
            self.store.event(db, "proposed", name, payload)

    def evaluate(self, name, pairs):
        identifier(name)
        if not isinstance(pairs, list) or len(pairs) < 3:
            raise ValueError("At least three paired approved runs are required")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM techniques WHERE id=?", (name,)).fetchone()
            if not row or row["state"] not in {"proposed", "evaluated"}:
                raise ValueError("Only proposed or evaluated techniques can be evaluated")
            proposal = json.loads(row["payload"])
        topics, runs, deltas, bindings = set(), set(), [], []
        for pair in pairs:
            baseline, candidate = self.store.run(pair["baseline"]), self.store.run(pair["candidate"])
            if baseline["status"] != "approved" or candidate["status"] != "approved":
                raise ValueError("Evaluation requires human-approved outputs")
            if baseline["brief"] != candidate["brief"]:
                raise ValueError("Paired runs must have exactly the same brief")
            if candidate["plan"]["technique"] != name or baseline["plan"]["technique"] == name:
                raise ValueError("Candidate technique provenance mismatch")
            if (baseline["plan"]["technique"] != proposal["baseline"] or
                    baseline["plan"]["technique_snapshot"] != proposal["baseline_snapshot"] or
                    candidate["plan"]["technique_snapshot"] != proposal):
                raise ValueError("Evaluation does not match the proposal's frozen baseline")
            def context(plan):
                return {"preferences": plan["preferences"],
                        "steps": [{k: step[k] for k in ["id", "capability", "dependencies", "model"]}
                                  for step in plan["steps"]]}
            if context(baseline["plan"]) != context(candidate["plan"]):
                raise ValueError("Paired evaluation must freeze model and preference context")
            topic = baseline["brief"]["topic"]
            if topic in topics or baseline["id"] in runs or candidate["id"] in runs:
                raise ValueError("Evaluation needs distinct topics and run pairs")
            topics.add(topic)
            runs.update([baseline["id"], candidate["id"]])
            for run in [baseline, candidate]:
                for step in run["steps"]:
                    self.engine.artifact(run["id"], step["result"])
                    for supplement in step["result"]["supplements"]:
                        self.engine.artifact(run["id"], supplement)
                bindings.append({"run": run["id"], "results": [s["result"] for s in run["steps"]]})
            a = bounded(pair["baseline_score"], 0, 1, "baseline_score")
            b = bounded(pair["candidate_score"], 0, 1, "candidate_score")
            if not isinstance(pair.get("rationale"), str) or len(pair["rationale"].strip()) < 10:
                raise ValueError("Each pair requires a review rationale of at least ten characters")
            deltas.append(b - a)
        mean = sum(deltas) / len(deltas)
        result = {"mean_delta": mean, "worst_delta": min(deltas), "pairs": pairs,
                  "bindings": bindings, "passed": mean >= 0.05 - 1e-9 and min(deltas) >= -0.1 - 1e-9,
                  "proposal": proposal, "method": "human-scored paired evaluation; not statistical proof"}
        with self.store.connect() as db:
            row = db.execute("SELECT state FROM techniques WHERE id=?", (name,)).fetchone()
            if not row or row[0] not in {"proposed", "evaluated"}:
                raise ValueError("Only proposed or evaluated techniques can be evaluated")
            db.execute("UPDATE techniques SET evaluation=?,state='evaluated' WHERE id=?", (json.dumps(result), name))
            self.store.event(db, "evaluated", name, result)
        return result

    def promote(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM techniques WHERE id=?", (name,)).fetchone()
            if not row or row["state"] != "evaluated" or not row["evaluation"]:
                raise ValueError("Technique must be evaluated before activation")
            evaluation = json.loads(row["evaluation"])
            if evaluation["proposal"] != json.loads(row["payload"]):
                raise ValueError("Proposal changed after evaluation")
            if not evaluation["passed"]:
                raise ValueError("Evaluation did not pass")
            for binding in evaluation["bindings"]:
                for result in binding["results"]:
                    self.engine.artifact(binding["run"], result)
                    for supplement in result["supplements"]:
                        self.engine.artifact(binding["run"], supplement)
            previous = db.execute("SELECT id FROM techniques WHERE state='active'").fetchone()
            if (previous[0] if previous else None) != evaluation["proposal"]["baseline"]:
                raise ValueError("Active baseline changed; evaluate a new proposal against the current baseline")
            db.execute("UPDATE techniques SET state='retired' WHERE state='active'")
            db.execute("UPDATE techniques SET state='active',previous_state=? WHERE id=?",
                       (previous[0] if previous else None, name))
            self.store.event(db, "promoted", name, {"previous": previous[0] if previous else None})

    def rollback(self, name):
        identifier(name)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM techniques WHERE id=? AND state='active'", (name,)).fetchone()
            if not row:
                raise ValueError("Only the active technique can be rolled back")
            db.execute("UPDATE techniques SET state='retired' WHERE id=?", (name,))
            if row["previous_state"]:
                db.execute("UPDATE techniques SET state='active' WHERE id=?", (row["previous_state"],))
            self.store.event(db, "rolled_back", name, {"restored": row["previous_state"]})
