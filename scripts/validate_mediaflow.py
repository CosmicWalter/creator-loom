"""Optional real MediaFlow/FFmpeg integration, with explicitly simulated inference.

Requires a separate MediaFlow checkout/environment. Uses temporary data and
new loopback listeners only; never imports existing settings or account data.
"""

import argparse
import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.mediaflow import Client, split_text
from creator_loom.routing import load_cards
from creator_loom.store import Store

TEXT = "A keeper sees a blue signal. A small mirror answers the signal."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mediaflow-source", type=Path, default=Path("../mediaflow"))
    parser.add_argument("--mediaflow-python", type=Path)
    args = parser.parse_args()
    source = args.mediaflow_source.resolve()
    # Preserve the venv entry point: resolving its symlink loses venv discovery.
    python = (args.mediaflow_python or source / ".venv/bin/python").absolute()
    if not python.is_file() or not (source / "mediaflow/app.py").is_file():
        raise SystemExit("Provide a MediaFlow checkout and its Python environment")
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0"*2400)
    wave_bytes = data.getvalue()
    counters = {"inference_submits": 0, "consuming_result_reads": 0, "drafts": 0}
    jobs = set()
    class SimulatedInference(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.path.endswith("chat/completions"):
                counters["drafts"] += 1
                return self.send({"choices": [{"message": {"content": TEXT}}]})
            counters["inference_submits"] += 1
            job_id = uuid.uuid4().hex
            jobs.add(job_id)
            self.send({"job_id": job_id})

        def do_GET(self):
            if self.path == "/health":
                return self.send({"ok": True})
            if "/tts/status/" in self.path:
                return self.send({"status": "done"})
            job_id = self.path.rsplit("/", 1)[-1]
            if job_id not in jobs:
                self.send_error(404)
                return
            jobs.remove(job_id)
            counters["consuming_result_reads"] += 1
            self.send(wave_bytes)
    server = ThreadingHTTPServer(("127.0.0.1", 0), SimulatedInference)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    inference_url = f"http://127.0.0.1:{server.server_port}"
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="loom-mediaflow-") as temp:
            root = Path(temp)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            endpoint = f"http://127.0.0.1:{port}"
            code = ('import sys; from pathlib import Path; import uvicorn; '
                    'from mediaflow.app import create_app; from mediaflow.core import Settings; '
                    'app=create_app(Settings(data=Path(sys.argv[1]),indextts_url=sys.argv[2],tts_timeout=15)); '
                    'uvicorn.run(app,host="127.0.0.1",port=int(sys.argv[3]),log_level="error")')
            process = subprocess.Popen([str(python), "-c", code, str(root/"service"), inference_url, str(port)],
                                       cwd=source, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Isolated MediaFlow process exited during startup")
                try:
                    Client(endpoint).json("GET", "/api/capabilities")
                    break
                except ValueError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Isolated MediaFlow did not become ready")
            reference = root/"reference.wav"
            reference.write_bytes(wave_bytes)
            receipt = Client(endpoint).upload_voice(reference, True)
            cards = load_cards(None) + [
                ModelCard("test-writer", "text", "chat", model="simulated-writer", endpoint=inference_url+"/v1",
                          local=True, max_output_chars=500),
                ModelCard("local-tts", "audio", "mediaflow", model="indextts", endpoint=endpoint, local=True,
                          voice=receipt["asset_id"], voice_authorized=True, segment_chars=40)]
            engine = Engine(Store(root/"loom"), cards)
            run_id = engine.create(Brief("Original synthetic lighthouse narration", "bookcast", local_only=True))
            result = engine.execute(run_id)
            deadline = time.monotonic()+30
            while result["status"] == "waiting_external" and time.monotonic() < deadline:
                time.sleep(0.25)
                result = engine.resume(run_id)
            if result["status"] != "needs_review":
                raise RuntimeError("MediaFlow integration did not finish")
            engine.approve(run_id)
            film = engine.artifact(run_id, result["steps"][-1]["result"])
            media = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(film)]))
            assert {s["codec_type"] for s in media["streams"]} == {"video", "audio"}
            expected = len(split_text(TEXT, 40))
            assert counters == {"inference_submits": expected, "consuming_result_reads": expected, "drafts": 1}
            print(json.dumps({"real_mediaflow": True, "real_ffmpeg": True, "inference": "simulated",
                              "review": "approved", **counters}))
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
