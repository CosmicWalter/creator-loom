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
from .lab import Lab, creative_tasks
from .series import Series
from .story_memory import StoryMemory
from .mediaflow import MediaFlow
from .timeline import Timeline
from . import timeline_media
from .assets import Assets
from .music import Music


TIMELINE_ERRORS = {
    "Series/memory changed or an episode is pending; finish it before editing memory": "系列或角色记忆已有变化，或仍有待完成章节。请查看当前版本，并先完成或拒绝待定章节。",
    "Series changed during character-memory review": "系列在审核期间已更新。草稿未写入，请检查当前版本后再决定。",
    "Fact quotation is not present in the bound evidence": "事实引用与所选原文不一致，请从证据原文逐字复制并检查。",
    "Fact evidence cannot cite an unvisited future source unit": "角色事实不能引用尚未进入创作进度的后续原文。",
    "A character needs 1–20 reviewed facts": "每个角色需保留 1–20 条已核对事实，或移除暂不使用的角色。",
    "Memory revision must change the reviewed character facts": "角色事实尚未改变，无需创建重复版本。",

    "Timeline changed; inspect the current version before editing or reviewing": "剪辑已有新版本。草稿仍保留，请查看当前版本后再决定如何保存。",
    "Caption cues must be ordered, non-overlapping and at least one millisecond": "请按时间顺序填写字幕，避免重叠，并让每条至少持续一毫秒。",
    "Caption text must be 1–500 plain characters without markup or control characters": "字幕需为 1–500 个纯文本字符，不能包含换行、尖括号或控制字符。",
    "Shot exceeds its source video duration": "镜头的入点加时长超出了源视频，请缩短时长或提前入点。",
    "Audio in point is outside its source": "音频入点已超出源音频，请提前入点。",
    "Only music from in=0 can loop": "只有从 0 秒开始的音乐音轨可以循环。",
    "Zoom motion currently requires a still image": "居中推近仅支持静态图片，视频片段请使用保持原画面。",
    "Approve every shot before sealing the edit": "请先让每个镜头审核通过；已否决的镜头需另存新版本修改。",
    "Shot decision is immutable; revise the edit": "已保存的镜头审核不可覆盖，请基于此版编辑并保存新版本。",
    "Timeline sources must be approved creative artifacts": "剪辑只能引用已审核通过的源作品，请先到作品档案检查。",
    "Local media tool unavailable or timed out; no remote operation was submitted": "本机媒体工具不可用或超时，请确认已安装 FFmpeg / FFprobe；没有提交远端任务。",
    "Timeline exceeds ten minutes": "剪辑总时长不能超过十分钟，请拆分为多份作品。",
    "Only draft shots can be reviewed": "这个版本已不能修改镜头审核，请检查版本或另存新版本。",
}


class Workbench:
    def __init__(self, store, cards):
        self.store, self.cards = store, cards
        self.engine = Engine(store, cards)
        self.library = Library(store)
        self.series = Series(store, self.engine)
        self.coach = Coach(store, self.engine)
        self.research = Research(store, Learning(store, self.engine))
        self.lab = Lab(store, cards)
        self.timeline = Timeline(store)
        self.assets = Assets(store)
        self.music = Music(store, cards)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-workbench")
        with store.connect() as db:
            db.execute("UPDATE web_timeline_actions SET status='interrupted',error='服务重启；请检查剪辑状态，未自动重新渲染。' WHERE status IN ('queued','running')")
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

    def action(self, run_id, operation, key, driver=None):
        identifier(key)
        self.store.run(run_id)
        if operation not in {"execute", "resume"} and not (driver and operation in {"experiment_baseline", "experiment_candidate"}):
            raise ValueError("Unknown execution operation")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM web_actions WHERE id=?", (key,)).fetchone()
            if prior:
                if prior["run_id"] != run_id or prior["operation"] != operation:
                    raise ValueError("Action key was used for another operation")
                return dict(prior)
            db.execute("INSERT INTO web_actions VALUES(?,?,?,'queued',NULL)", (key, run_id, operation))
        self.pool.submit(self._execute, key, run_id, operation, driver)
        return {"id": key, "status": "queued"}

    def _execute(self, key, run_id, operation, driver=None):
        with self.store.connect() as db:
            db.execute("UPDATE web_actions SET status='running' WHERE id=?", (key,))
        try:
            driver() if driver else getattr(self.engine, operation)(run_id)
            state, error = "done", None
        except Exception:
            state, error = "error", "执行已停止。已有产物和远端凭据已保留，请查看任务状态。"
        with self.store.connect() as db:
            db.execute("UPDATE web_actions SET status=?,error=? WHERE id=?", (state, error, key))

    def timeline_assets(self, profile):
        with self.store.connect() as db:
            rows = []
            for row in db.execute("SELECT id,brief FROM runs WHERE status='approved' ORDER BY rowid DESC"):
                if json.loads(row["brief"])["profile"] == profile:
                    rows.append(row)
                    if len(rows) == 300:
                        break
        assets, checked, unavailable = [], 0, 0
        for row in rows:
            brief = json.loads(row["brief"])
            if brief["profile"] != profile:
                continue
            if checked == 300:
                break
            checked += 1
            run = self.store.run(row["id"])
            try:
                self.engine.verify_artifacts(run)
            except (OSError, ValueError):
                unavailable += 1
                continue
            for step in run["steps"]:
                for index, result in enumerate([step["result"], *step["result"]["supplements"]]):
                    suffix = Path(result["file"]).suffix
                    if suffix not in {".png", ".ppm", ".mp4", ".wav"}:
                        continue
                    slot = "main" if index == 0 else "s"+str(index-1)
                    key = run["id"]+"/"+step["id"]+"/"+slot
                    assets.append({"key": key, "title": brief["topic"], "stage": step["id"],
                                   "kind": "audio" if suffix == ".wav" else "video" if suffix == ".mp4" else "image",
                                   "ref": {"run": run["id"], "step": step["id"], "file": result["file"], "sha256": result["sha256"]}})
        unavailable_assets = 0
        for asset in self.assets.list(profile, "approved"):
            try:
                ref, _, payload = self.assets.reference({"asset": asset["id"]})
            except (OSError, ValueError):
                unavailable_assets += 1
                continue
            assets.append({"key": "asset/"+asset["id"], "title": payload["title"], "stage": "imported", "kind": payload["kind"], "ref": ref})
        return {"assets": assets, "unavailable_runs": unavailable, "unavailable_assets": unavailable_assets,
                "scope": "Most recent 300 approved runs and 300 approved imported assets in this preference profile"}

    def timeline_source(self, key):
        if key.startswith("asset/"):
            ref, path, payload = self.assets.reference({"asset": key.split("/")[1]})
            return {"ref": ref, "kind": payload["kind"], "duration": payload["duration"], "preview": "/api/assets/"+ref["asset"]+"/media"}, path
        run_id, step_id, slot = key.split("/")
        run = self.store.run(run_id)
        step = next((s for s in run["steps"] if s["id"] == step_id), None)
        if not step or not step["result"]:
            raise ValueError("Unknown source artifact")
        result = step["result"] if slot == "main" else step["result"]["supplements"][int(slot[1:])]
        ref = {"run": run_id, "step": step_id, "file": result["file"], "sha256": result["sha256"]}
        suffix = Path(result["file"]).suffix
        ref, path, info = self.timeline.reference(ref, "audio" if suffix == ".wav" else "visual")
        kind = "audio" if suffix == ".wav" else "video" if suffix == ".mp4" else "image"
        value = {"ref": ref, "kind": kind, "duration": None if kind == "image" else timeline_media.duration(info, "audio" if kind == "audio" else "video"),
                 "preview": ("/api/timeline-previews/" if suffix == ".ppm" else "/api/artifacts/")+key}
        return value, path

    def timeline_detail(self, name, version=None):
        result = self.timeline.inspect(name, version)
        with self.store.connect() as db:
            result["actions"] = [dict(r) for r in db.execute("SELECT * FROM web_timeline_actions WHERE timeline_id=? AND version=? ORDER BY rowid DESC LIMIT 10", (name, result["version"]))]
        return result

    def timeline_action(self, name, version, key):
        identifier(key)
        if type(version) is not int:
            raise ValueError("Timeline version must be an integer")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM web_timeline_actions WHERE id=?", (key,)).fetchone()
            if prior:
                if prior["timeline_id"] != name or prior["version"] != version:
                    raise ValueError("Render key was used for another timeline/version")
                return dict(prior)
            timeline = self.timeline.inspect(name)
            self.timeline.require_current(timeline, version)
            if timeline["state"] not in {"sealed", "needs_review", "approved"}:
                raise ValueError("Seal the reviewed timeline before rendering")
            db.execute("INSERT INTO web_timeline_actions VALUES(?,?,?,'queued',NULL)", (key, name, version))
        self.pool.submit(self._render_timeline, key, name, version)
        return {"id": key, "status": "queued", "timeline_id": name, "version": version}

    def _render_timeline(self, key, name, version):
        with self.store.connect() as db:
            db.execute("UPDATE web_timeline_actions SET status='running' WHERE id=?", (key,))
        try:
            self.timeline.render(name, version)
            status, error = "done", None
        except Exception:
            status, error = "error", "剪辑未完成。请检查镜头版本、审核与素材状态；旧版产物已保留。"
        with self.store.connect() as db:
            db.execute("UPDATE web_timeline_actions SET status=?,error=? WHERE id=?", (status, error, key))

    def get(self, path, query):
        profile = identifier(query.get("profile", ["default"])[0])
        if path == "/api/practice":
            return self.coach.practice_list(profile)
        match = re.fullmatch(r"/api/practice-reviews/([A-Za-z0-9_-]+)(/report)?", path)
        if match:
            return self.coach.review_report(match[1]) if match[2] else self.coach.review_inspect(match[1])
        if path == "/api/assets":
            return self.assets.list(profile, query.get("state", [None])[0])
        match = re.fullmatch(r"/api/assets/([A-Za-z0-9_-]+)", path)
        if match:
            return self.assets.inspect(match[1])
        if path == "/api/music":
            return self.music.list(profile)
        match = re.fullmatch(r"/api/music/([A-Za-z0-9_-]+)", path)
        if match:
            return self.music.inspect(match[1])
        if path == "/api/timeline-assets":
            return self.timeline_assets(profile)
        match = re.fullmatch(r"/api/timeline-assets/(asset/[A-Za-z0-9_-]+|[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/(?:main|s\d+))", path)
        if match:
            return self.timeline_source(match[1])[0]
        if path == "/api/timelines":
            with self.store.connect() as db:
                rows = db.execute("""SELECT t.id,t.current_version,v.state,v.spec FROM timelines t
                  JOIN timeline_versions v ON v.timeline_id=t.id AND v.version=t.current_version
                  WHERE t.profile=? ORDER BY t.rowid DESC LIMIT 300""", (profile,)).fetchall()
            return [{"id": r["id"], "version": r["current_version"], "state": r["state"],
                     "title": json.loads(r["spec"])["title"], "duration": json.loads(r["spec"])["duration"]} for r in rows]
        match = re.fullmatch(r"/api/timelines/([A-Za-z0-9_-]+)", path)
        if match:
            return self.timeline_detail(match[1], int(query["version"][0]) if "version" in query else None)
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
                if run["plan"].get("benchmark"):
                    trial = db.execute("SELECT protocol FROM benchmarks WHERE id=?", (run["plan"]["benchmark"]["id"],)).fetchone()
                    run["experiment_lab"] = json.loads(trial["protocol"]).get("lab") if trial else None
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
        match = re.fullmatch(r"/api/series/([A-Za-z0-9_-]+)/memory", path)
        if match:
            result = StoryMemory(self.store).inspect(match[1], int(query["version"][0]) if "version" in query else None)
            result["evidence_options"] = StoryMemory(self.store).evidence_options(match[1])
            return result
        if path.startswith("/api/series/"):
            return self.series.inspect(path.rsplit("/", 1)[-1])
        if path == "/api/research":
            return {"items": self.research.inbox("all")[:200], "sources": self.research.sources(), "labs": self.lab.list(profile), "tasks": list(creative_tasks())}
        match = re.fullmatch(r"/api/labs/([A-Za-z0-9_-]+)(/draft)?", path)
        if match:
            return self.lab.draft(match[1]) if match[2] else self.lab.inspect(match[1])
        raise ValueError("Unknown endpoint")

    def post(self, path, body, key):
        match = re.fullmatch(r"/api/practice/([A-Za-z0-9_-]+)/blind", path)
        if match:
            return self.coach.new_review(match[1])
        match = re.fullmatch(r"/api/practice-reviews/([A-Za-z0-9_-]+)/score", path)
        if match:
            return self.coach.score_review(match[1], body["scores"], body["reviewer_kind"], body["rationale"])
        if path == "/api/labs":
            identifier(key)
            return self.lab.create(body["id"], body["spec"], key)
        match = re.fullmatch(r"/api/labs/([A-Za-z0-9_-]+)/(accept|experiment|evaluate|promote|rollback|seal)", path)
        if match:
            name, operation = match.groups()
            if operation == "accept":
                return self.lab.accept(name, body["technique"], body["review"])
            if operation == "experiment":
                return self.lab.experiment(name, body["settings"])
            if operation == "evaluate":
                return self.lab.evaluate(name)
            if operation in {"promote", "rollback"}:
                return self.lab.activate(name, rollback=operation == "rollback")
            trial = self.lab.trial(name)
            return self.lab.benchmarks.seal_development(trial["id"])
        match = re.fullmatch(r"/api/labs/([A-Za-z0-9_-]+)/cases/([A-Za-z0-9_-]+)/(baseline|candidate|review|approve)", path)
        if match:
            name, case_id, operation = match.groups()
            trial = self.lab.trial(name)
            case = next((c for c in trial["cases"] if c["id"] == case_id), None)
            if not case:
                raise ValueError("Unknown experiment case")
            if operation == "approve":
                return self.lab.approve_case(name, case_id)
            if operation == "review":
                return self.lab.benchmarks.review(trial["id"], case_id, body["scores"], body["rationale"])
            self.lab.benchmarks.accessible(trial, case)
            return self.action(case[operation+"_run"], "experiment_"+operation, key,
                               driver=lambda: self.lab.benchmarks.generate(trial["id"], case_id, operation))
        if path == "/api/assets":
            identifier(key)
            raw = base64.b64decode(body["data"], validate=True)
            if len(raw) > 32*1024*1024:
                raise ValueError("Workbench media uploads are limited to 32 MB; use the CLI for sources up to 64 MB")
            return self.assets.import_bytes(raw, body["metadata"], key)
        match = re.fullmatch(r"/api/assets/([A-Za-z0-9_-]+)/(review|derive)", path)
        if match:
            if match[2] == "review":
                return self.assets.review(match[1], body["decision"], body["note"])
            identifier(key)
            return self.assets.derive_audio(match[1], body["settings"], key)
        if path == "/api/music":
            identifier(key)
            return self.music.create(body["id"], body["spec"], key)
        match = re.fullmatch(r"/api/music/([A-Za-z0-9_-]+)/(handoff|external|attach)", path)
        if match:
            name, operation = match.groups()
            if operation == "handoff":
                return self.music.handoff(name, body.get("transfer_authorized"), body["note"], body.get("include_audio", False))
            if operation == "external":
                return self.music.external(name, body["reference"], body["note"])
            return self.music.attach(name, body["asset"], body["note"])
        if path == "/api/timelines":
            identifier(key)
            return self.timeline.create(body["id"], body["spec"], body.get("profile", "default"), request_key=key)
        match = re.fullmatch(r"/api/timelines/([A-Za-z0-9_-]+)/(revise|shot|seal|render|approve)", path)
        if match:
            name, operation = match.groups()
            version = body["version"]
            if operation == "revise":
                identifier(key)
                return self.timeline.revise(name, body["spec"], version, request_key=key)
            if operation == "shot":
                return self.timeline.review_shot(name, body["shot"], version, body["decision"], body["note"])
            if operation == "render":
                return self.timeline_action(name, version, key)
            return getattr(self.timeline, operation)(name, version)
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
        match = re.fullmatch(r"/api/series/([A-Za-z0-9_-]+)/memory(?:/(evidence))?", path)
        if match:
            memory = StoryMemory(self.store)
            if match[2]:
                return {"text": memory.evidence_text(match[1], body["reference"])}
            return memory.update(match[1], body["payload"], body["series_version"], body["memory_version"], body["note"], body.get("reviewed"))
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
            if parsed.path in {"/", "/app.js", "/app.css", "/timeline.js", "/media.js", "/lab.js", "/practice.js", "/memory.js"}:
                name = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css", "/timeline.js": "timeline.js", "/media.js": "media.js", "/lab.js": "lab.js", "/practice.js": "practice.js", "/memory.js": "memory.js"}[parsed.path]
                raw = (Path(__file__).parent/"static"/name).read_bytes()
                mime = {"index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css", "timeline.js": "text/javascript", "media.js": "text/javascript", "lab.js": "text/javascript", "practice.js": "text/javascript", "memory.js": "text/javascript"}[name]
                self.headers_for(200, mime+"; charset=utf-8", len(raw))
                return self.wfile.write(raw)
            if not self.trusted():
                return self.respond(403, {"error": "只允许本机工作台访问。"})
            if not self.authorized():
                return self.respond(401, {"error": "请输入本机工作台访问码。"})
            if parsed.path == "/api/session":
                return self.respond(200, {"authenticated": True})
            match = re.fullmatch(r"/api/practice-reviews/([A-Za-z0-9_-]+)/(packet|A|B)", parsed.path)
            if match:
                name, label = match.groups()
                coach = self.server.app.coach
                if label == "packet":
                    raw = coach.review_packet(name)
                    self.headers_for(200, "application/zip", len(raw), {"Content-Disposition": 'attachment; filename="creator-loom-practice-review.zip"'})
                    return self.wfile.write(raw)
                review = coach.review_load(name)
                run = coach.verify_review(review)
                version = review["display_order"][["A", "B"].index(label)]
                return self.stream_file(coach.engine.artifact(run["id"], review["binding"][version]))
            match = re.fullmatch(r"/api/labs/([A-Za-z0-9_-]+)/cases/([A-Za-z0-9_-]+)/(A|B|packet)", parsed.path)
            if match:
                name, case_id, label = match.groups()
                trial = self.server.app.lab.trial(name)
                bench = self.server.app.lab.benchmarks
                if label == "packet":
                    raw = bench.packet_bytes(trial["id"], case_id)
                    self.headers_for(200, "application/zip", len(raw), {"Content-Disposition": 'attachment; filename="creator-loom-blind-review.zip"'})
                    return self.wfile.write(raw)
                target = bench.target_artifact(trial["id"], case_id, label)
                if target.suffix == ".ppm":
                    raw = timeline_media.command(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", "ppm_pipe", "-i", str(target), "-frames:v", "1", "-vf", "scale=640:360:force_original_aspect_ratio=decrease,setsar=1", "-map_metadata", "-1", "-f", "image2pipe", "-c:v", "png", "-threads", "1", "pipe:1"], timeout=20)
                    bench.target_artifact(trial["id"], case_id, label)
                    self.headers_for(200, "image/png", len(raw))
                    return self.wfile.write(raw)
                return self.stream_file(target)
            match = re.fullmatch(r"/api/assets/([A-Za-z0-9_-]+)/export", parsed.path)
            if match:
                raw = self.server.app.assets.bundle(match[1])
                self.headers_for(200, "application/zip", len(raw), {"Content-Disposition": 'attachment; filename="creator-loom-media-asset.zip"'})
                return self.wfile.write(raw)
            match = re.fullmatch(r"/api/assets/([A-Za-z0-9_-]+)/media", parsed.path)
            if match:
                _, target = self.server.app.assets.verify(match[1])
                return self.stream_file(target)
            match = re.fullmatch(r"/api/music/([A-Za-z0-9_-]+)/handoff", parsed.path)
            if match:
                raw = self.server.app.music.handoff_bytes(match[1])
                self.headers_for(200, "application/zip", len(raw), {"Content-Disposition": 'attachment; filename="creator-loom-music-handoff.zip"'})
                return self.wfile.write(raw)
            if re.fullmatch(r"/api/artifacts/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/(?:main|s\d+)", parsed.path):
                return self.artifact(parsed.path)
            match = re.fullmatch(r"/api/timeline-media/([A-Za-z0-9_-]+)/(\d+)/(film\.mp4|captions\.srt|captions\.vtt|timeline\.json)", parsed.path)
            if match:
                name, version, filename = match.groups()
                timeline = self.server.app.timeline.inspect(name, int(version))
                if timeline["state"] not in {"needs_review", "approved"}:
                    raise ValueError("Timeline render is not ready")
                self.server.app.timeline.verify_outputs(timeline)
                if filename == "captions.vtt":
                    if not timeline["spec"]["captions"]:
                        raise ValueError("Timeline has no captions")
                    raw = timeline_media.vtt(timeline["spec"]["captions"]).encode()
                    self.headers_for(200, "text/vtt; charset=utf-8", len(raw))
                    return self.wfile.write(raw)
                if filename not in {o["file"] for o in timeline["outputs"]}:
                    raise ValueError("Unknown output")
                return self.stream_file(self.server.app.timeline.directory(name, int(version))/filename)
            match = re.fullmatch(r"/api/timeline-export/([A-Za-z0-9_-]+)/(\d+)", parsed.path)
            if match:
                raw = self.server.app.timeline.bundle(match[1], int(match[2]))
                self.headers_for(200, "application/zip", len(raw), {"Content-Disposition": 'attachment; filename="creator-loom-timeline.zip"'})
                return self.wfile.write(raw)
            match = re.fullmatch(r"/api/timeline-previews/([A-Za-z0-9_-]+/[A-Za-z0-9_-]+/(?:main|s\d+))", parsed.path)
            if match:
                value, source = self.server.app.timeline_source(match[1])
                if source.suffix != ".ppm":
                    raise ValueError("Only PPM needs a derived image preview")
                raw = timeline_media.command(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                     "-format_whitelist", "ppm_pipe", "-i", str(source), "-frames:v", "1", "-vf", "scale=640:360:force_original_aspect_ratio=decrease,setsar=1",
                     "-map_metadata", "-1", "-f", "image2pipe", "-c:v", "png", "-threads", "1", "pipe:1"], timeout=20)
                self.server.app.timeline.reference(value["ref"], "visual")
                self.headers_for(200, "image/png", len(raw))
                return self.wfile.write(raw)
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
        return self.stream_file(target)

    def stream_file(self, target):
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
        mime = "text/plain; charset=utf-8" if target.suffix in {".md", ".json", ".txt", ".srt"} else mimetypes.guess_type(target.name)[0] or "application/octet-stream"
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
            limit = 46*1024*1024 if self.path == "/api/assets" else 12*1024*1024
            if not 0 < length <= limit or self.headers.get_content_type() != "application/json":
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
            if isinstance(exc, ValueError) and str(exc) in TIMELINE_ERRORS:
                message = TIMELINE_ERRORS[str(exc)]
            return self.respond(409, {"error": message})
