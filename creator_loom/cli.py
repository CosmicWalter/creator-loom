from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .domain import Brief, RECIPES, identifier
from .coaching import Coach
from .engine import Engine
from .learning import Learning, discover
from .routing import load_cards
from .store import Store


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Creator Loom — inspect, create, review, learn")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["plan", "create"]:
        p = sub.add_parser(command)
        p.add_argument("topic")
        p.add_argument("--format", choices=RECIPES, default="article")
        p.add_argument("--language", default="zh")
        p.add_argument("--profile", default="default")
        p.add_argument("--budget", type=float, default=1.0)
        p.add_argument("--max-latency", type=float, default=300)
        p.add_argument("--local-only", action="store_true")
        p.add_argument("--technique", help="Explicit experimental technique ID")
    for command in ["execute", "inspect", "approve"]:
        sub.add_parser(command).add_argument("run")
    p = sub.add_parser("feedback")
    p.add_argument("run")
    p.add_argument("step")
    p.add_argument("rating", type=float)
    p = sub.add_parser("preferences")
    p.add_argument("profile")
    p.add_argument("--set", help='JSON object, e.g. {"tone":"concise"}')
    sub.add_parser("forget").add_argument("profile")
    sub.add_parser("models")
    sub.add_parser("discover").add_argument("feed")
    p = sub.add_parser("propose")
    p.add_argument("id")
    p.add_argument("--source", required=True)
    p.add_argument("--guidance", required=True)
    p = sub.add_parser("evaluate")
    p.add_argument("id")
    p.add_argument("--pairs", type=Path, required=True)
    for command in ["promote", "rollback"]:
        sub.add_parser(command).add_argument("id")
    sub.add_parser("techniques")
    sub.add_parser("coach").add_argument("run")
    p = sub.add_parser("practice")
    p.add_argument("run")
    p.add_argument("step")
    p.add_argument("--revision", type=Path, required=True)
    p.add_argument("--dimension", required=True)
    p.add_argument("--before", type=float, required=True)
    p.add_argument("--after", type=float, required=True)
    p.add_argument("--rationale", required=True)
    sub.add_parser("progress").add_argument("profile")
    args = parser.parse_args(argv)
    try:
        store = Store(args.data)
        cards = load_cards(args.config)
        engine = Engine(store, cards)
        learning = Learning(store, engine)
        coach = Coach(store, engine)
        if args.command in {"plan", "create"}:
            brief = Brief(args.topic, args.format, args.language, args.profile, args.budget,
                          args.local_only, args.max_latency)
            if args.command == "plan":
                emit(engine.plan(brief, args.technique))
            else:
                emit({"run": engine.create(brief, args.technique), "status": "ready",
                      "next": "Inspect the plan, then explicitly execute the run"})
        elif args.command == "execute":
            emit(engine.execute(args.run))
        elif args.command == "inspect":
            emit(store.run(args.run))
        elif args.command == "approve":
            engine.approve(args.run)
            emit({"status": "approved", "published": False})
        elif args.command == "feedback":
            store.feedback(args.run, args.step, args.rating)
            emit({"status": "recorded", "scope": "profile and capability"})
        elif args.command == "preferences":
            identifier(args.profile)
            if args.set:
                values = json.loads(args.set)
                if not isinstance(values, dict) or len(json.dumps(values)) > 4000:
                    raise ValueError("Preferences must be a JSON object of at most 4000 characters")
                store.set_preferences(args.profile, values)
            emit(store.preferences(args.profile))
        elif args.command == "forget":
            identifier(args.profile)
            store.forget(args.profile)
            emit({"status": "preferences_and_routing_feedback_deleted",
                  "retained": "creative runs, artifacts, practice, evaluations and audit events"})
        elif args.command == "models":
            emit([m.to_dict() for m in cards])
        elif args.command == "discover":
            emit(discover(args.feed))
        elif args.command == "propose":
            learning.propose(args.id, args.source, args.guidance)
            emit({"state": "proposed"})
        elif args.command == "evaluate":
            emit(learning.evaluate(args.id, json.loads(args.pairs.read_text())))
        elif args.command == "promote":
            learning.promote(args.id)
            emit({"state": "active"})
        elif args.command == "rollback":
            learning.rollback(args.id)
            emit({"state": "retired"})
        elif args.command == "techniques":
            with store.connect() as db:
                emit([dict(r) for r in db.execute("SELECT * FROM techniques ORDER BY id")])
        elif args.command == "coach":
            emit(coach.workbook(args.run))
        elif args.command == "practice":
            emit(coach.record(args.run, args.step, args.revision, args.dimension,
                              args.before, args.after, args.rationale))
        elif args.command == "progress":
            emit(coach.progress(args.profile))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        # Provider exceptions never expose their bodies; config and local errors remain actionable.
        print(f"loom: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
