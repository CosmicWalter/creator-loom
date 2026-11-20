"""Authenticated single-user loopback workbench, with no external web dependencies."""

from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .coaching import Coach
from .delivery import delivery
from .domain import Brief, RECIPES, identifier
from .engine import Engine
from .learning import Learning
from .library import Library
from .locking import run_lock
from .research import Research
from .series import Series
from .mediaflow import MediaFlow


class Workbench:
    def __init__(self, store, cards):
        self.store, self.cards = store, cards
        self.engine = Engine(store, cards)
        self.library = Library(store)
        self.series = Series(store, self.engine)
        self.coach = Coach(store, self.engine)
        self.research = Research(store, Learning(store, self.engine))
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-workbench")
        with store.connect() as db:
            db.execute("UPDATE web_actions SET status='interrupted',error='服务重启；未自动重做。' WHERE status IN ('queued','running')")

    def plan(self, body):
        brief = Brief(**body["brief"])
        context = self.library.context(body["book"], body.get("unit", 0), body.get("continuity", "")) if body.get("book") else None
        plan = self.engine.plan(brief, body.get("technique"), context)
        draft_id = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("INSERT INTO web_drafts VALUES(?,?,?)", (draft_id, json.dumps(plan, ensure_ascii=False), time.time()+1800))
        return {"draft": draft_id, "plan": plan}

    def create(self, draft_id, key):
        identifier(key)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM web_submissions WHERE id=?", (key,)).fetchone()
            if prior:
                if prior["draft_id"] != draft_id:
                    raise ValueError("Creation key was used for another plan")
                return {"run": prior["run_id"]}
            draft = db.execute("SELECT * FROM web_drafts WHERE id=?", (draft_id,)).fetchone()
            if not draft or draft["expires"] < time.time():
                raise ValueError("Plan preview expired; preview again before creating")
            run_id = uuid.uuid4().hex
            self.engine.persist(db, run_id, json.loads(draft["plan"]))
            db.execute("INSERT INTO web_submissions VALUES(?,?,?)", (key, draft_id, run_id))
        return {"run": run_id}

    def action(self, run_id, operation, key):
        identifier(key)
        self.store.run(run_id)
        if operation not in {"execute", "resume"}:
            raise ValueError("Unknown execution operation")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM web_actions WHERE id=?", (key,)).fetchone()
            if prior:
                if prior["run_id"] != run_id or prior["operation"] != operation:
                    raise ValueError("Action key was used for another operation")
                return dict(prior)
            db.execute("INSERT INTO web_actions VALUES(?,?,?,'queued',NULL)", (key, run_id, operation))
        self.pool.submit(self._execute, key, run_id, operation)
        return {"id": key, "status": "queued"}

    def _execute(self, key, run_id, operation):
        with self.store.connect() as db:
            db.execute("UPDATE web_actions SET status='running' WHERE id=?", (key,))
        try:
            getattr(self.engine, operation)(run_id)
            state, error = "done", None
        except Exception:
            state, error = "error", "执行已停止。已有产物和远端凭据已保留，请查看任务状态。"
        with self.store.connect() as db:
            db.execute("UPDATE web_actions SET status=?,error=? WHERE id=?", (state, error, key))

    def get(self, path, query):
        profile = identifier(query.get("profile", ["default"])[0])
        if path == "/api/overview":
            with self.store.connect() as db:
                runs = []
                for row in db.execute("SELECT id,brief,status,created FROM runs ORDER BY rowid DESC"):
                    brief = json.loads(row["brief"])
                    if brief["profile"] == profile:
                        runs.append({**dict(row), "brief": brief})
                    if len(runs) == 300:
                        break
                books = [{**dict(r), "units": len(json.loads(r["units"]))} for r in db.execute("SELECT id,title,format,rights,units FROM books ORDER BY rowid DESC")]
                series = [{**dict(r), "definition": json.loads(r["definition"])} for r in db.execute("SELECT id,definition,cursor,version,pending_run FROM series ORDER BY rowid DESC")]
                series = [s for s in series if s["definition"]["brief"]["profile"] == profile]
                for s in series:
                    s["unit_count"] = next((b["units"] for b in books if b["id"] == s["definition"]["book_id"]), 0)
                    s["completed"] = s["cursor"] >= s["unit_count"]
            return {"runs": runs, "books": books, "series": series,
                    "models": [{"id": m.id, "capability": m.capability, "local": m.local,
                                "available": m.enabled and (not m.api_key_env or bool(os.environ.get(m.api_key_env)))
                                             and (m.adapter != "mediaflow" or m.voice_authorized)} for m in self.cards],
                    "formats": list(RECIPES), "progress": self.coach.progress(profile)}
        if path.startswith("/api/runs/"):
            run_id = path.split("/")[3]
            run = self.store.run(run_id)
            with self.store.connect() as db:
                run["events"] = [{**dict(r), "payload": json.loads(r["payload"])} for r in db.execute("SELECT kind,payload,created FROM events WHERE subject=? ORDER BY id DESC LIMIT 30", (run_id,))]
                run["actions"] = [dict(r) for r in db.execute("SELECT * FROM web_actions WHERE run_id=? ORDER BY rowid DESC LIMIT 10", (run_id,))]
            return run
        if path.startswith("/api/actions/"):
            with self.store.connect() as db:
                row = db.execute("SELECT * FROM web_actions WHERE id=?", (path.rsplit("/", 1)[-1],)).fetchone()
            if not row:
                raise ValueError("Unknown action")
            return dict(row)
        if path.startswith("/api/remote/"):
            run_id = path.rsplit("/", 1)[-1]
            self.store.run(run_id)
            with self.store.connect() as db:
                rows = db.execute("SELECT * FROM remote_batches WHERE run_id=?", (run_id,)).fetchall()
            return [{"step": r["step_id"], "segments": [{"index": i, "status": s["status"],
                     "job_id": s["job_id"], "text": s["request"]["text"]}
                     for i, s in enumerate(json.loads(r["payload"])["segments"])]} for r in rows]
        if path.startswith("/api/books/"):
            book_id = path.rsplit("/", 1)[-1]
            return self.library.context(book_id, int(query["unit"][0])) if "unit" in query else self.library.inspect(book_id)
        if path.startswith("/api/series/"):
            return self.series.inspect(path.rsplit("/", 1)[-1])
        if path == "/api/research":
            return {"items": self.research.inbox("all")[:200], "sources": self.research.sources()}
        raise ValueError("Unknown endpoint")

    def post(self, path, body, key):
        if path == "/api/plans":
            return self.plan(body)
        if path == "/api/runs":
            return self.create(body["draft"], key)
        if path == "/api/books":
            if body.get("format") not in {"txt", "epub"}:
                raise ValueError("Only TXT and EPUB are supported")
            raw = base64.b64decode(body["data"], validate=True)
            if len(raw) > 8*1024*1024:
                raise ValueError("Book upload exceeds 8 MB")
            with tempfile.TemporaryDirectory() as temp:
                source = Path(temp)/("source."+body["format"])
                source.write_bytes(raw)
                return self.library.import_book(source, body["title"], body["rights"], body.get("rights_note", ""))
        if path == "/api/series":
            return self.series.create(body["book"], Brief(**body["brief"]), body.get("continuity", ""), body.get("start_unit", 0))
        if path.startswith("/api/series/"):
            _, _, _, series_id, operation = path.split("/")
            if operation == "next":
                return {"run": self.series.next(series_id)}
            if operation == "accept":
                return self.series.accept(series_id, body["run"], body["continuity"], body["version"])
        if path.startswith("/api/runs/"):
            _, _, _, run_id, operation = path.split("/")
            if operation in {"execute", "resume"}:
                return self.action(run_id, operation, key)
            if operation == "approve":
                existing = self.store.run(run_id)
                if existing["status"] == "approved":
                    self.engine.verify_artifacts(existing)
                else:
                    self.engine.approve(run_id)
                return {"status": "approved"}
            if operation == "feedback":
                self.store.feedback(run_id, body["step"], body["rating"])
                return {"status": "recorded"}
            if operation == "coach":
                return self.coach.workbook(run_id)
            if operation == "reconcile":
                return self.engine.reconcile_mediaflow(run_id, body["step"], body["segment"], body["job"])
            if operation == "practice":
                spec = next((s for s in self.store.run(run_id)["plan"]["steps"] if s["id"] == body["step"]), None)
                if not spec or spec["capability"] != "text":
                    raise ValueError("Workbench revision editor supports text steps only")
                if len(body["revision"]) > 100000:
                    raise ValueError("Revision is too large")
                with tempfile.TemporaryDirectory() as temp:
                    revision = Path(temp)/"revision.txt"
                    revision.write_text(body["revision"])
                    return self.coach.record(run_id, body["step"], revision, body["dimension"], body["before"], body["after"], body["rationale"])
        if path == "/api/research/propose":
            return self.research.review(body["item"], body["revision"], body["note"], body["technique"], body["guidance"])
        raise ValueError("Unknown endpoint")


def create_server(store, cards, port=8787):
    guard = run_lock(store, "workbench")
    guard.__enter__()
    try:
        app = Workbench(store, cards)
        server = LocalServer(("127.0.0.1", port), Handler)
    except Exception:
        guard.__exit__(None, None, None)
        raise
    server.app, server.guard = app, guard
    server.code, server.session = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    server.started = time.time()
    server.expires = time.time()+28800
    server.origin = f"http://127.0.0.1:{server.server_port}"
    return server


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_close(self):
        super().server_close()
        if hasattr(self, "app"):
            self.app.pool.shutdown(wait=True, cancel_futures=True)
            self.guard.__exit__(None, None, None)


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "CreatorLoom", ""
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *args):
        pass

    def headers_for(self, status, mime, size, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", (extra or {}).get("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"))
        for k, v in (extra or {}).items():
            if k != "Content-Security-Policy":
                self.send_header(k, v)
        self.end_headers()

    def respond(self, status, body, extra=None):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.headers_for(status, "application/json; charset=utf-8", len(raw), extra)
        self.wfile.write(raw)

    def trusted(self):
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            return False
        if self.headers.get("Origin") not in {None, self.server.origin}:
            return False
        return self.headers.get("Sec-Fetch-Site") not in {"cross-site"}

    def authorized(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            value = cookie.get("loom_session")
            return bool(value and hmac.compare_digest(value.value, self.server.session) and time.time() < self.server.expires)
        except Exception:
            return False

    def do_GET(self):
        try:
            if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
                return self.respond(403, {"error": "只允许本机工作台访问。"})
            parsed = urlsplit(self.path)
            if parsed.path in {"/", "/app.js", "/app.css"}:
                name = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css"}[parsed.path]
                raw = (Path(__file__).parent/"static"/name).read_bytes()
                mime = {"index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css"}[name]
                self.headers_for(200, mime+"; charset=utf-8", len(raw))
                return self.wfile.write(raw)
            if not self.trusted():
                return self.respond(403, {"error": "只允许本机工作台访问。"})
            if not self.authorized():
                return self.respond(401, {"error": "请输入本机工作台访问码。"})
            if parsed.path == "/api/session":
                return self.respond(200, {"authenticated": True})
            if re.fullmatch(r"/api/artifacts/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/(?:main|s\d+)", parsed.path):
                return self.artifact(parsed.path)
            if re.fullmatch(r"/api/export/[A-Za-z0-9_-]+", parsed.path):
                raw = delivery(self.server.app.engine, parsed.path.rsplit("/", 1)[-1])
                self.headers_for(200, "application/zip", len(raw), {"Content-Disposition": 'attachment; filename="creator-loom-delivery.zip"'})
                return self.wfile.write(raw)
            return self.respond(200, self.server.app.get(parsed.path, parse_qs(parsed.query)))
        except (BrokenPipeError, ConnectionResetError):
            return
        except (ValueError, KeyError, TypeError, IndexError, OSError, sqlite3.Error):
            return self.respond(409, {"error": "无法读取此内容，请刷新并确认任务、审核状态或产物完整性。"})

    def artifact(self, path):
        _, _, _, run_id, step_id, slot = path.split("/")
        run = self.server.app.store.run(run_id)
        step = next((s for s in run["steps"] if s["id"] == step_id), None)
        if not step or not step["result"]:
            raise ValueError("No artifact for this step")
        result = step["result"] if slot == "main" else step["result"]["supplements"][int(slot[1:])]
        target = self.server.app.engine.artifact(run_id, result)
        size = target.stat().st_size
        start, end, status = 0, size-1, 200
        if self.headers.get("Range"):
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers["Range"])
            if not match or not (match[1] or match[2]):
                return self.respond(416, {"error": "Unsupported range"})
            if not match[1]:
                suffix = int(match[2])
                start = max(0, size-suffix)
            else:
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
            if not 0 <= start <= end < size:
                return self.respond(416, {"error": "Invalid range"})
            status = 206
        headers = {"Accept-Ranges": "bytes"}
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        mime = "text/plain; charset=utf-8" if target.suffix in {".md", ".json", ".txt"} else mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.headers_for(status, mime, end-start+1, headers)
        with target.open("rb") as file:
            file.seek(start)
            left = end-start+1
            while left:
                raw = file.read(min(left, 65536))
                if not raw:
                    break
                self.wfile.write(raw)
                left -= len(raw)

    def do_POST(self):
        try:
            if not self.trusted() or self.headers.get("X-Loom-Request") != "1":
                self.close_connection = True
                return self.respond(403, {"error": "请求来源未被允许。"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 12*1024*1024 or self.headers.get_content_type() != "application/json":
                self.close_connection = True
                return self.respond(413, {"error": "请求格式或大小不受支持。"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected object")
            if self.path == "/api/session":
                if not isinstance(body.get("code"), str) or not hmac.compare_digest(body["code"], self.server.code):
                    return self.respond(401, {"error": "访问码不正确。"})
                self.server.expires = time.time()+28800
                return self.respond(200, {"authenticated": True}, {"Set-Cookie": f"loom_session={self.server.session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"})
            if not self.authorized():
                return self.respond(401, {"error": "本机会话已过期，请重新连接。"})
            result = self.server.app.post(self.path, body, self.headers.get("Idempotency-Key", ""))
            return self.respond(200, result)
        except (ValueError, KeyError, TypeError, IndexError, OSError, sqlite3.Error) as exc:
            message = "操作未完成。请检查输入、模型可用性、版本和任务状态；已保存内容不会自动重做。"
            if isinstance(exc, ValueError) and str(exc).startswith("No eligible "):
                message = "没有符合当前要求的模型。请检查已启用的模型配置、本地选项、输入长度和预算。"
            elif isinstance(exc, ValueError) and str(exc).startswith("No complete workflow"):
                message = "现有模型组合无法同时满足预算、延迟与输入长度，请调整要求后重新预览。"
            return self.respond(409, {"error": message})
