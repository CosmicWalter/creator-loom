"""Bounded method inheritance with hashed baseline references and legacy reads."""

import json

from .evidence import digest


def baseline(store, payload):
    value = payload.get("baseline_snapshot")
    if isinstance(value, dict) and set(value) == {"reference", "sha256"}:
        if value["reference"] != payload.get("baseline"):
            raise ValueError("Editorial baseline reference mismatch")
        with store.connect() as db:
            row = db.execute("SELECT payload FROM techniques WHERE id=?", (value["reference"],)).fetchone()
        if not row:
            raise ValueError("Editorial baseline record is missing")
        result = json.loads(row["payload"])
        if digest(result) != value["sha256"]:
            raise ValueError("Editorial baseline snapshot changed")
        return result
    # Existing databases retain their inline snapshots; new writes use references.
    return value


def resolve(store, name, payload, task):
    for _ in range(32):
        if payload is None:
            return None
        if not payload.get("task_scope") or task in payload["task_scope"]:
            return {"id": name, "guidance": payload["guidance"]}
        if "inherited_methods" in payload:
            return payload["inherited_methods"].get(task)
        name, payload = payload.get("baseline"), baseline(store, payload)
    raise ValueError("Legacy editorial inheritance exceeds its supported depth")
