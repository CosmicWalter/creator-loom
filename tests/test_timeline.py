"""Real local media editing with original synthetic media, not model inference."""

import io
import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters
from creator_loom.cli import main
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.store import Store
from creator_loom.timeline import Timeline
from creator_loom import timeline_media as media


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
class TimelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"state")
        self.timeline = Timeline(self.store)
        self.cards = [ModelCard("graphic", "image", "cover", local=True),
                      ModelCard("writer", "text", "chat", model="test-writer", endpoint="http://127.0.0.1:8765/v1", local=True),
                      ModelCard("voice", "audio", "speech", model="test-voice", endpoint="http://127.0.0.1:8765/v1", local=True),
                      ModelCard("film", "video", "render", local=True)]
        self.engine = Engine(self.store, self.cards)
        self.color = (220, 30, 20)
        self.frequency = 440
        self.fake = patch.object(adapters, "execute", self.fixture_output)
        self.fake.start()
        self.addCleanup(self.fake.stop)
        self.image = self.source("cover", "cover")

    def fixture_output(self, card, prompt, dependencies, directory, key=""):
        directory.mkdir(parents=True, exist_ok=True)
        if card.capability == "text":
            path = directory/"content.md"
            path.write_text("An original synthetic narration for media mechanics tests.")
        elif card.capability == "image":
            path = directory/"cover.ppm"
            path.write_bytes(b"P6\n320 180\n255\n"+bytes(self.color)*320*180)
        elif card.capability == "audio":
            path = directory/"narration.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                audio.writeframes(b"".join(struct.pack('<h', round(4000*math.sin(i*2*math.pi*self.frequency/48000))) for i in range(48000)))
        else:
            path = directory/"film.mp4"
            media.command(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1", "-metadata", "title=private-source-tag", str(path)])
        return path

    def source(self, fmt, step):
        run = self.engine.create(Brief("Original licensed media fixture", fmt, local_only=True))
        self.engine.execute(run)
        self.engine.approve(run)
        saved = next(s for s in self.store.run(run)["steps"] if s["id"] == step)
        return {"run": run, "step": step, "file": saved["result"]["file"]}

    def spec(self):
        return {"title": "Original timeline fixture", "width": 640, "height": 360, "fps": 24,
                "shots": [{"id": "first", "source": self.image, "duration": 0.5}], "captions": []}

    def seal(self, name="edit"):
        timeline = self.timeline.inspect(name)
        for shot in timeline["spec"]["shots"]:
            self.timeline.review_shot(name, shot["id"], timeline["version"], "approve", "Reviewed framing and timing.")
        return self.timeline.seal(name, timeline["version"])

    def test_versioned_edit_rejects_stale_updates_and_resets_reviews(self):
        self.timeline.create("edit", self.spec())
        self.timeline.review_shot("edit", "first", 1, "approve", "Framing reviewed.")
        spec = self.timeline.inspect("edit")["spec"]
        spec["title"] = "A revised creative title"
        revised = self.timeline.revise("edit", spec, 1)
        self.assertEqual(revised["version"], 2)
        self.assertEqual(revised["reviews"], [])
        self.assertEqual(self.timeline.inspect("edit", 1)["spec"]["title"], "Original timeline fixture")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.timeline.revise("edit", spec, 1)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.timeline.review_shot("edit", "first", 1, "approve", "Stale review.")
        self.assertEqual(len(self.timeline.inspect("edit", 1)["reviews"]), 1)

    def test_review_and_delivery_gates_and_immutable_shot_decisions(self):
        self.timeline.create("edit", self.spec())
        for op in [lambda: self.timeline.seal("edit", 1), lambda: self.timeline.render("edit", 1),
                   lambda: self.timeline.approve("edit", 1), lambda: self.timeline.export("edit")]:
            with self.assertRaises(ValueError):
                op()
        self.timeline.review_shot("edit", "first", 1, "reject", "Framing needs revision.")
        with self.assertRaises(Exception):
            self.timeline.review_shot("edit", "first", 1, "approve", "Cannot overwrite review.")
        with self.assertRaises(ValueError):
            self.timeline.seal("edit", 1)
        self.assertEqual(self.timeline.inspect("edit")["reviews"][0]["decision"], "reject")

    def test_sources_must_be_approved_bound_supported_artifacts(self):
        spec = self.spec()
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status='needs_review' WHERE id=?", (self.image["run"],))
        with self.assertRaisesRegex(ValueError, "approved"):
            self.timeline.create("edit", spec)
        self.engine.approve(self.image["run"])
        spec["shots"][0]["source"] = {**self.image, "file": "../private.txt"}
        with self.assertRaises(ValueError):
            self.timeline.create("edit", spec)
        spec["shots"][0]["source"] = {**self.image, "sha256": "changed"}
        with self.assertRaises(ValueError):
            self.timeline.create("edit", spec)

    def test_invalid_edit_constraints(self):
        changes = [lambda s: s.update(width=1024), lambda s: s.update(fps=True),
                   lambda s: s["shots"][0].update(duration=0.51),
                   lambda s: s["shots"][0].update(duration=float('nan')),
                   lambda s: s["shots"][0].update(motion="untrusted-filter"),
                   lambda s: s["shots"][0].update(**{"in": 0.1}),
                   lambda s: s.update(captions=[{"start": 0, "end": 0.5, "text": "<b>markup</b>"}]),
                   lambda s: s.update(captions=[{"start": 0, "end": 0.6, "text": "Outside edit"}]),
                   lambda s: s.update(captions=[{"start": 0.2, "end": 0.4, "text": "One"}, {"start": 0.3, "end": 0.5, "text": "Overlap"}])]
        for change in changes:
            spec = self.spec()
            change(spec)
            with self.assertRaises(ValueError):
                self.timeline.create("edit", spec)
        with self.assertRaises(ValueError):
            self.timeline.inspect("edit")

    def test_actual_two_shot_cuts_subtitles_mixed_audio_and_neutral_export(self):
        self.color = (20, 210, 30)
        second = self.source("cover", "cover")
        narration = self.source("podcast", "narration")
        self.frequency = 880
        music = self.source("podcast", "narration")
        spec = self.spec()
        spec["shots"].append({"id": "second", "source": second, "duration": 1.5, "motion": "zoom-in"})
        spec["narration"] = {"source": narration, "gain": 0.8}
        spec["music"] = {"source": music, "gain": 0.2, "loop": True}
        spec["captions"] = [{"start": 0, "end": 0.45, "text": "原创镜头一"}, {"start": 0.5, "end": 2, "text": "Original second shot"}]
        self.timeline.create("edit", spec)
        self.seal()
        rendered = self.timeline.render("edit", 1)
        self.assertEqual(rendered["state"], "needs_review")
        film = self.timeline.directory("edit", 1)/"film.mp4"
        info = media.probe(film)
        self.assertEqual({s["codec_type"] for s in info["streams"]}, {"video", "audio", "subtitle"})
        self.assertAlmostEqual(media.duration(info, "video"), 2, delta=0.05)
        for position, dominant in [(0.2, 0), (0.7, 1)]:
            rgb = media.command(["ffmpeg", "-v", "error", "-ss", str(position), "-i", str(film), "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
            self.assertEqual(max(range(3), key=lambda i: rgb[i]), dominant)
        # Decode the actual mixed signal and check both distinct source tones.
        pcm = media.command(["ffmpeg", "-v", "error", "-i", str(film), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"])
        samples = struct.unpack('<'+'h'*(len(pcm)//2), pcm)
        def tones(start, end):
            segment = samples[round(start*48000):round(end*48000)]
            return [abs(sum(x*complex(math.cos(i*2*math.pi*f/48000), -math.sin(i*2*math.pi*f/48000)) for i, x in enumerate(segment)))/len(segment) for f in [440, 880, 2200]]
        first, tail = tones(0.1, 0.8), tones(1.2, 1.8)
        self.assertGreater(first[0], first[1]*2)
        self.assertGreater(first[1], first[2]*10)
        self.assertGreater(tail[1], tail[2]*10)
        self.assertLess(tail[0], tail[1]/10)
        with self.assertRaises(ValueError):
            self.timeline.export("edit")
        self.timeline.approve("edit", 1)
        with patch.object(media, "render", side_effect=AssertionError("Must not rerender")):
            self.assertEqual(self.timeline.render("edit", 1)["state"], "approved")
        bundle = self.timeline.export("edit")["file"]
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(set(archive.namelist()), {"film.mp4", "captions.srt", "timeline.json"})
            edit = archive.read("timeline.json").decode()
            for forbidden in ["endpoint", "profile", self.image["run"], narration["run"], str(self.store.root)]:
                self.assertNotIn(forbidden, edit)
            self.assertIn("原创镜头一", archive.read("captions.srt").decode())
            for item in archive.infolist():
                self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))

    def test_zoom_changes_actual_frames_and_failed_render_preserves_sources(self):
        # Replace the fixture with a bounded original grid, then rebind its review.
        run = self.store.run(self.image["run"])
        path = self.engine.artifact(run["id"], run["steps"][0]["result"])
        pixels = bytearray()
        for y in range(180):
            for x in range(320):
                pixels.extend((240, 220, 40) if (x//16+y//16)%2 else (20, 40, 190))
        path.write_bytes(b"P6\n320 180\n255\n"+pixels)
        import hashlib
        with self.store.connect() as db:
            result = run["steps"][0]["result"]
            result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            db.execute("UPDATE steps SET result=? WHERE run_id=?", (json.dumps(result), run["id"]))
        spec = self.spec()
        spec["shots"][0]["motion"] = "zoom-in"
        self.timeline.create("edit", spec)
        self.seal()
        self.timeline.render("edit", 1)
        film = self.timeline.directory("edit", 1)/"film.mp4"
        frames = [media.command(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(film), "-frames:v", "1", "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]) for t in [0, 0.4]]
        self.assertGreater(sum(abs(a-b) for a, b in zip(*frames))/len(frames[0]), 10)
        self.timeline.revise("edit", self.spec(), 1)
        self.seal()
        with patch.object(media, "render", side_effect=RuntimeError("Private tool error must not escape")):
            with self.assertRaisesRegex(ValueError, "sources were preserved"):
                self.timeline.render("edit", 2)
        self.assertEqual(self.timeline.inspect("edit")["state"], "failed")
        self.engine.verify_artifacts(self.store.run(self.image["run"]))
        self.assertEqual(self.timeline.inspect("edit", 1)["state"], "needs_review")

    def test_real_video_clip_trimming_and_source_metadata_removal(self):
        clip = self.source("bookcast", "film")
        spec = self.spec()
        spec["shots"] = [{"id": "clip", "source": clip, "in": 1, "duration": 0.5}]
        self.timeline.create("edit", spec)
        self.seal()
        self.timeline.render("edit", 1)
        film = self.timeline.directory("edit", 1)/"film.mp4"
        tags = json.loads(media.command(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(film)]))
        self.assertNotIn("private-source-tag", json.dumps(tags))
        self.assertAlmostEqual(media.duration(media.probe(film), "video"), 0.5, delta=0.05)
        spec["shots"][0]["in"] = 1.9
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.timeline.revise("edit", spec, 1)

    def test_source_and_output_tampering_block_review_and_delivery(self):
        self.timeline.create("edit", self.spec())
        self.seal()
        self.timeline.render("edit", 1)
        film = self.timeline.directory("edit", 1)/"film.mp4"
        original = film.read_bytes()
        film.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.timeline.approve("edit", 1)
        film.write_bytes(original)
        self.timeline.approve("edit", 1)
        run = self.store.run(self.image["run"])
        self.engine.artifact(run["id"], run["steps"][0]["result"]).write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.timeline.export("edit")

    def test_interrupted_render_is_not_replayed_and_live_lock_is_respected(self):
        self.timeline.create("edit", self.spec())
        self.seal()
        with self.timeline.lock("edit"):
            with self.assertRaisesRegex(ValueError, "lock"):
                self.timeline.render("edit", 1)
        with self.store.connect() as db:
            db.execute("UPDATE timeline_versions SET state='rendering' WHERE timeline_id='edit'")
        with patch.object(media, "render", side_effect=AssertionError("No replay")):
            with self.assertRaisesRegex(ValueError, "interrupted"):
                self.timeline.render("edit", 1)
        self.assertEqual(self.timeline.inspect("edit")["state"], "interrupted")
        self.assertEqual(self.timeline.revise("edit", self.spec(), 1)["version"], 2)

    def test_cli_create_and_inspect(self):
        path = Path(self.temp.name)/"edit.json"
        path.write_text(json.dumps(self.spec()))
        prefix = ["--data", str(self.store.root)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(prefix+["timeline-new", "cli-edit", "--spec", str(path)]), 0)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(prefix+["timeline-inspect", "cli-edit"]), 0)
        self.assertEqual(json.loads(out.getvalue())["spec"]["duration"], 0.5)


if __name__ == "__main__":
    unittest.main()
