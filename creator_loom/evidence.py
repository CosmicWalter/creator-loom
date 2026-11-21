"""Immutable public-feed evidence bindings, with an optional current-version gate."""

import hashlib
import json

from .domain import identifier
from .feeds import source_url


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def freeze(store, requests):
    if not isinstance(requests, list) or not 1 <= len(requests) <= 4:
        raise ValueError("Select one to four explicit evidence revisions")
    sources, seen = [], set()
    with store.connect() as db:
        for request in requests:
            if not isinstance(request, dict) or set(request) != {"item", "revision"} or type(request["revision"]) is not int:
                raise ValueError("Evidence needs an item ID and integer revision")
            identifier(request["item"])
            row = db.execute("SELECT * FROM research_items WHERE id=?", (request["item"],)).fetchone()
            if not row or row["revision"] != request["revision"] or row["state"] == "dismissed" or request["item"] in seen:
                raise ValueError("Evidence changed, is dismissed, duplicated or missing")
            seen.add(request["item"])
            sources.append({"item": row["id"], "revision": row["revision"], "sha256": row["sha256"], "snapshot": json.loads(row["payload"])})
    validate(store, sources, current=True)
    return sources


def validate(store, sources, current=False):
    if not isinstance(sources, list) or not 1 <= len(sources) <= 4:
        raise ValueError("Invalid frozen evidence list")
    with store.connect() as db:
        seen = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"item", "revision", "sha256", "snapshot"} or type(source["revision"]) is not int:
                raise ValueError("Invalid evidence binding")
            identifier(source["item"])
            if source["item"] in seen or digest(source["snapshot"]) != source["sha256"]:
                raise ValueError("Evidence snapshot changed or is duplicated")
            seen.add(source["item"])
            source_url(source["snapshot"]["source"])
            row = db.execute("SELECT payload,sha256 FROM research_revisions WHERE item_id=? AND revision=?", (source["item"], source["revision"])).fetchone()
            if not row or row["sha256"] != source["sha256"] or json.loads(row["payload"]) != source["snapshot"]:
                raise ValueError("Frozen evidence provenance is missing or changed")
            if current:
                latest = db.execute("SELECT revision,state FROM research_items WHERE id=?", (source["item"],)).fetchone()
                if not latest or latest["revision"] != source["revision"] or latest["state"] == "dismissed":
                    raise ValueError("Evidence changed or was dismissed; start a new synthesis")
