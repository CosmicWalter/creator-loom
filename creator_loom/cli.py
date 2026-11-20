from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from .domain import Brief, RECIPES, identifier
from .coaching import Coach
from .engine import Engine
from .learning import Learning, discover
from .routing import load_cards
from .store import Store
from .library import Library
from .series import Series
from .research import Research


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def brief_arguments(parser):
    parser.add_argument("topic")
    parser.add_argument("--format", choices=RECIPES, default="article")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--budget", type=float, default=1.0)
    parser.add_argument("--max-latency", type=float, default=300)
    parser.add_argument("--local-only", action="store_true")


def brief_from(args):
    return Brief(args.topic, args.format, args.language, args.profile, args.budget,
                 args.local_only, args.max_latency)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Creator Loom — inspect, create, review, learn")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["plan", "create"]:
        p = sub.add_parser(command)
        brief_arguments(p)
        p.add_argument("--technique", help="Explicit experimental technique ID")
        p.add_argument("--book", help="Explicitly authorized imported book ID")
        p.add_argument("--unit", type=int, default=0)
        p.add_argument("--continuity", default="")
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
    p = sub.add_parser("discover")
    p.add_argument("feed")
    p.add_argument("--transport", choices=["urllib", "curl"], default="urllib")
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
    p = sub.add_parser("metrics")
    p.add_argument("--profile", default="default")
    p.add_argument("--run")
    p = sub.add_parser("book-import")
    p.add_argument("file", type=Path)
    p.add_argument("--title", required=True)
    p.add_argument("--rights", choices=["owned", "licensed", "public-domain"], required=True)
    p.add_argument("--rights-note", default="")
    p.add_argument("--unit-chars", type=int, default=4000)
    p = sub.add_parser("book-inspect")
    p.add_argument("book")
    p.add_argument("--unit", type=int)
    p = sub.add_parser("series-new")
    p.add_argument("book")
    brief_arguments(p)
    p.add_argument("--continuity", default="")
    p.add_argument("--start-unit", type=int, default=0)
    p = sub.add_parser("series-next")
    p.add_argument("series")
    p.add_argument("--technique")
    sub.add_parser("series-inspect").add_argument("series")
    p = sub.add_parser("series-accept")
    p.add_argument("series")
    p.add_argument("run")
    p.add_argument("--base-version", type=int, required=True)
    p.add_argument("--continuity", required=True)
    p = sub.add_parser("series-reject")
    p.add_argument("series")
    p.add_argument("run")
    p.add_argument("--base-version", type=int, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--provider-checked", action="store_true")
    p = sub.add_parser("source-add")
    p.add_argument("id")
    p.add_argument("url")
    p.add_argument("--keyword", action="append", default=[])
    p.add_argument("--interval", type=int, default=21600)
    p.add_argument("--transport", choices=["urllib", "curl"], default="urllib")
    sub.add_parser("sources")
    p = sub.add_parser("source-set")
    p.add_argument("id")
    p.add_argument("--base-version", type=int, required=True)
    flags = p.add_mutually_exclusive_group(required=True)
    flags.add_argument("--enabled", action="store_true")
    flags.add_argument("--disabled", action="store_true")
    words = p.add_mutually_exclusive_group()
    words.add_argument("--keyword", action="append")
    words.add_argument("--clear-keywords", action="store_true")
    p.add_argument("--interval", type=int)
    p.add_argument("--transport", choices=["urllib", "curl"])
    p = sub.add_parser("research-refresh")
    p.add_argument("source", nargs="?")
    p = sub.add_parser("research-worker")
    p.add_argument("--watch", action="store_true", help="Run foreground due-source polling until interrupted")
    p.add_argument("--poll-seconds", type=int, default=60)
    p = sub.add_parser("research-inbox")
    p.add_argument("--state", choices=["inbox", "dismissed", "proposed", "changed", "all"], default="inbox")
    sub.add_parser("research-show").add_argument("item")
    for command in ["research-dismiss", "research-reopen", "research-propose"]:
        p = sub.add_parser(command)
        p.add_argument("item")
        p.add_argument("--base-revision", type=int, required=True)
        p.add_argument("--note", required=True)
        if command == "research-propose":
            p.add_argument("technique")
            p.add_argument("--guidance", required=True)
    args = parser.parse_args(argv)
    try:
        store = Store(args.data)
        cards = load_cards(args.config)
        engine = Engine(store, cards)
        learning = Learning(store, engine)
        coach = Coach(store, engine)
        library = Library(store)
        series = Series(store, engine)
        research = Research(store, learning)
        if args.command in {"plan", "create"}:
            brief = brief_from(args)
            if not args.book and (args.unit != 0 or args.continuity):
                raise ValueError("--unit and --continuity require an imported --book")
            context = library.context(args.book, args.unit, args.continuity) if args.book else None
            if args.command == "plan":
                emit(engine.plan(brief, args.technique, context))
            else:
                emit({"run": engine.create(brief, args.technique, context), "status": "ready",
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
            emit({"status": "recorded", "scope": "profile, format:stage and model signature"})
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
            emit({"status": "preferences_routing_feedback_and_measurements_deleted",
                  "retained": "research subscriptions/evidence, books, series continuity, creative runs, artifacts (including embedded metrics), practice, evaluations and audit events"})
        elif args.command == "models":
            emit([m.to_dict() for m in cards])
        elif args.command == "discover":
            emit(discover(args.feed, args.transport))
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
        elif args.command == "metrics":
            emit(store.metrics(args.profile, args.run))
        elif args.command == "book-import":
            emit(library.import_book(args.file, args.title, args.rights, args.rights_note, args.unit_chars))
        elif args.command == "book-inspect":
            emit(library.context(args.book, args.unit) if args.unit is not None else library.inspect(args.book))
        elif args.command == "series-new":
            emit(series.create(args.book, brief_from(args), args.continuity, args.start_unit))
        elif args.command == "series-next":
            run_id = series.next(args.series, args.technique)
            emit({"run": run_id, "status": store.run(run_id)["status"],
                  "next": "Inspect and execute the existing run; repeated series-next reuses it"})
        elif args.command == "series-inspect":
            emit(series.inspect(args.series))
        elif args.command == "series-accept":
            emit(series.accept(args.series, args.run, args.continuity, args.base_version))
        elif args.command == "series-reject":
            emit(series.reject(args.series, args.run, args.base_version, args.reason, args.provider_checked))
        elif args.command == "source-add":
            emit(research.subscribe(args.id, args.url, args.keyword, args.interval, args.transport))
        elif args.command == "sources":
            emit(research.sources())
        elif args.command == "source-set":
            emit(research.configure(args.id, args.base_version, args.enabled,
                                    [] if args.clear_keywords else args.keyword, args.interval, args.transport))
        elif args.command == "research-refresh":
            emit(research.refresh(args.source) if args.source else research.tick())
        elif args.command == "research-worker":
            if not 1 <= args.poll_seconds <= 60:
                raise ValueError("Worker poll interval must be 1–60 seconds")
            while True:
                emit(research.tick())
                if not args.watch:
                    break
                try:
                    time.sleep(args.poll_seconds)
                except KeyboardInterrupt:
                    break
        elif args.command == "research-inbox":
            emit(research.inbox(args.state))
        elif args.command == "research-show":
            emit(research.inspect(args.item))
        elif args.command in {"research-dismiss", "research-reopen", "research-propose"}:
            emit(research.review(args.item, args.base_revision, args.note,
                                 getattr(args, "technique", None), getattr(args, "guidance", None),
                                 args.command == "research-reopen"))
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        # Provider exceptions never expose their bodies; config and local errors remain actionable.
        print(f"loom: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
