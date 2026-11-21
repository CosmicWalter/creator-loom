"""Original synthetic media and simulated text inference; no Suno quality claims."""

import io
import json
import math
import shutil
import struct
import tempfile
import unittest
import uuid
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

from creator_loom import adapters, timeline_media as media
from creator_loom.assets import Assets
from creator_loom.domain import Brief, ModelCard
from creator_loom.engine import Engine
from creator_loom.music import Music
from creator_loom.store import Store
from creator_loom.timeline import Timeline


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required")
class AssetsMusicTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root/"data")
        self.assets = Assets(self.store)
        self.cards = [ModelCard("writer", "text", "chat", model="fixture", local=True,
                               endpoint="http://127.0.0.1:8765/v1", max_chars=30000)]
        self.music = Music(self.store, self.cards)
        self.engine = Engine(self.store, self.cards)
        self.raw = self.wav()

    def wav(self):
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            audio.writeframes(b"".join(struct.pack('<h', round(4000*math.sin(i*2*math.pi*440/48000))) for i in range(96000)))
        return stream.getvalue()

    def meta(self, **extra):
        return {"title": "Original reference fixture", "kind": "audio", "rights": "owned", "rights_note": "Original synthetic test tone, authorized for editing.", "authorized": True, **extra}

    def approved(self, **extra):
        asset = self.assets.import_bytes(self.raw, self.meta(**extra))
        self.assets.review(asset["id"], "approve", "Content, provenance and rights reviewed.")
        return self.assets.inspect(asset["id"])

    def fake_writer(self, card, prompt, dependencies, directory, key=""):
        directory.mkdir(parents=True, exist_ok=True)
        output = directory/"content.md"
        output.write_text("Original simulated lyric or musical direction. No audio was analyzed.")
        (directory/"provider-usage.json").write_text('{"private": "operational metadata"}')
        return output

    def project(self, source=None, **overrides):
        spec = {"title": "Original music experiment", "intent": "Adapt this original lyric as a gentle instrumental-led story.",
                "lyrics": "A lantern lights the quiet sea.", "lyrics_rights": "owned", "rights_note": "Original test lyric and synthetic source, authorized for adaptation.", "adaptation_authorized": True}
        spec.update(overrides)
        if source:
            spec["source"] = {"asset": source["id"]}
        return self.music.create("music-test", spec)

    def execute_project(self, project):
        with patch.object(adapters, "execute", self.fake_writer):
            self.engine.execute(project["run_id"])
        self.engine.approve(project["run_id"])

    def test_import_requires_rights_and_idempotency_binds_content_and_metadata(self):
        for override in [{"authorized": False}, {"rights_note": ""}, {"rights": "licensed"}, {"origin": {"service": "suno", "reference": "https://suno.com/song/example?token=private"}}]:
            with self.assertRaises(ValueError):
                self.assets.import_bytes(self.raw, self.meta(**override))
        first = self.assets.import_bytes(self.raw, self.meta(), "stable-import")
        again = self.assets.import_bytes(self.raw, self.meta(), "stable-import")
        self.assertEqual(first["id"], again["id"])
        with self.assertRaises(ValueError):
            self.assets.import_bytes(self.raw, self.meta(title="Changed metadata"), "stable-import")
        self.assertEqual(len(self.assets.list("default")), 1)
        self.assertEqual(self.assets.list("other"), [])
        with self.assertRaises(ValueError):
            self.assets.reference({"asset": first["id"]}, "audio")
        self.assets.review(first["id"], "approve", "Original reference approved.")
        self.assets.review(first["id"], "approve", "Original reference approved.")
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.assets.review(first["id"], "reject", "Cannot overwrite approval.")

    def test_private_filename_and_source_tags_do_not_enter_normalized_media_or_credits(self):
        source = self.root/"private-input-name.wav"
        source.write_bytes(self.raw)
        tagged = self.root/"tagged.wav"
        media.command(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-metadata", "artist=private-source-tag", str(tagged)])
        asset = self.assets.import_file(tagged, self.meta(rights="licensed", attribution="Original synthetic tone; reuse permitted by this test fixture."))
        self.assets.review(asset["id"], "approve", "Checked attribution and actual output.")
        _, normalized = self.assets.verify(asset["id"], approved=True)
        details = media.command(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(normalized)]).decode()
        self.assertNotIn("private-source-tag", details)
        credits = json.dumps(self.assets.credits(asset["id"]))
        self.assertIn("Original synthetic tone", credits)
        self.assertNotIn("rights_note", credits)
        self.assertNotIn("private-input-name", json.dumps(asset))
        self.assertNotIn(str(self.root), json.dumps(asset))
        self.assertEqual(normalized.name, "audio.wav")
        self.assertAlmostEqual(asset["payload"]["duration"], 2, delta=0.01)

    def test_real_image_video_and_mp3_import(self):
        for kind, filename, generation in [
            ("image", "image.png", ["-f", "lavfi", "-i", "color=c=green:s=64x64", "-frames:v", "1", "-c:v", "png", "-threads", "1"]),
            ("video", "video.mp4", ["-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24:d=0.5", "-c:v", "libx264", "-threads", "1"]),
            ("audio", "audio.mp3", ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libmp3lame"]),
        ]:
            path = self.root/filename
            media.command(["ffmpeg", "-nostdin", "-v", "error", "-y", *generation, str(path)])
            asset = self.assets.import_file(path, self.meta(kind=kind))
            self.assets.review(asset["id"], "approve", "Reviewed normalized fixture.")
            ref, result, payload = self.assets.reference({"asset": asset["id"]})
            self.assertEqual(ref["kind"], kind)
            self.assertIn(result.suffix, {".png", ".mp4", ".wav"})
            self.assertEqual(payload["source_sha256"], __import__('hashlib').sha256(path.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            self.assets.import_bytes(b"Not a supported media file", self.meta())

    def test_audio_pitch_tempo_and_tape_edits_use_real_frequency_and_duration(self):
        source = self.approved()
        for settings, expected_frequency, expected_duration in [
            ({"start": 0, "duration": 2, "semitones": 12, "tempo": 1}, 880, 2),
            ({"duration": 1, "semitones": 0, "tempo": 0.5}, 440, 2),
            ({"duration": 1, "tempo": 0.5, "mode": "tape"}, 220, 2),
        ]:
            asset = self.assets.derive_audio(source["id"], settings)
            self.assertEqual(asset["state"], "needs_review")
            self.assertEqual(asset["payload"]["parent"]["asset"], source["id"])
            _, path = self.assets.verify(asset["id"])
            info = media.probe(path)
            self.assertAlmostEqual(media.duration(info, "audio"), expected_duration, delta=0.12)
            pcm = media.command(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"])
            samples = struct.unpack('<'+'h'*(len(pcm)//2), pcm)[12000:60000]
            crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
            self.assertAlmostEqual(crossings*48000/len(samples), expected_frequency, delta=3)
        with self.assertRaises(ValueError):
            self.assets.derive_audio(source["id"], {"mode": "tape", "semitones": 2})
        with self.assertRaises(ValueError):
            self.assets.derive_audio(source["id"], {"start": 1.5, "duration": 1})

    def test_music_plan_binds_audio_without_sending_it_and_handoff_is_explicit(self):
        source = self.approved(rights="licensed", attribution="Original synthetic source credit.")
        project = self.project(source)
        run = self.store.run(project["run_id"])
        self.assertEqual(run["plan"]["input_assets"][0]["asset"], source["id"])
        self.assertEqual([s["task"] for s in run["plan"]["steps"]], ["song:lyrics", "song:direction"])
        self.assertIn("have not heard", run["brief"]["topic"])
        self.assertNotIn("rights_note", run["brief"]["topic"])
        with self.assertRaises(ValueError):
            self.music.handoff(project["id"], True, "Explicit transfer approved.")
        self.execute_project(project)
        with self.assertRaises(ValueError):
            self.music.handoff(project["id"], False, "Transfer not authorized.")
        prepared = self.music.handoff(project["id"], True, "Authorized local handoff only.", include_audio=False)
        self.assertFalse(prepared["handoff"]["remote_submitted"])
        self.music.handoff(project["id"], True, "Authorized local handoff only.", include_audio=False)
        with zipfile.ZipFile(io.BytesIO(self.music.handoff_bytes(project["id"]))) as archive:
            self.assertEqual(set(archive.namelist()), {"lyrics.md", "direction.md", "brief.json"})
            manifest = archive.read("brief.json").decode()
            self.assertIn("Original synthetic source credit.", manifest)
            for private in ["rights_note", project["run_id"], source["id"], "endpoint", "provider-usage"]:
                self.assertNotIn(private, manifest)
            self.assertTrue(all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in archive.infolist()))
        with self.assertRaises(ValueError):
            self.music.handoff(project["id"], True, "Authorized local handoff only.", include_audio=True)

    def test_suno_result_is_operator_reported_and_requires_matching_reviewed_audio(self):
        project = self.project(); self.execute_project(project)
        self.music.handoff(project["id"], True, "Explicit handoff authorized for this plan.")
        reference = "https://suno.com/song/12345678-1234-1234-1234-123456789abc"
        reported = self.music.external(project["id"], reference, "Operator reports this public result reference.")
        self.assertIn("not verified", reported["external"]["evidence"])
        wrong = self.approved()
        with self.assertRaises(ValueError):
            self.music.attach(project["id"], wrong["id"], "Wrong origin should not attach.")
        result = self.approved(origin={"service": "suno", "reference": reference})
        attached = self.music.attach(project["id"], result["id"], "Actual local audio reviewed and adopted.")
        self.assertEqual(attached["state"], "result_attached")
        self.assertIn("operator-reported", attached["result"]["evidence"])
        self.assertEqual(attached["result"]["source"]["asset"], result["id"])
        with self.assertRaises(ValueError):
            self.music.external(project["id"], "https://suno.com/song/another-result", "Cannot change a frozen result.")

    def test_licensed_lyric_credit_is_preserved_and_uncredited_results_cannot_attach(self):
        project = self.project(lyrics_rights="licensed", lyrics_attribution="Original authorized lyric fixture credit.", lyrics_license_url="https://example.com/original-license")
        self.execute_project(project)
        self.music.handoff(project["id"], True, "Explicit external transfer with attribution preserved.")
        with zipfile.ZipFile(io.BytesIO(self.music.handoff_bytes(project["id"]))) as archive:
            self.assertIn("Original authorized lyric fixture credit.", archive.read("brief.json").decode())
        reference = "https://suno.com/song/12345678-1234-1234-1234-123456789abc"
        self.music.external(project["id"], reference, "Operator reports this declared external result.")
        origin = {"service": "suno", "reference": reference}
        missing = self.approved(origin=origin)
        with self.assertRaisesRegex(ValueError, "attribution"):
            self.music.attach(project["id"], missing["id"], "Uncredited local result must not be adopted.")
        credited = self.approved(origin=origin, attribution="Original authorized lyric fixture credit.\nhttps://example.com/original-license")
        self.assertEqual(self.music.attach(project["id"], credited["id"], "Reviewed result with required lyric credits.")["state"], "result_attached")

    def test_source_tampering_blocks_generation_derived_media_and_handoff(self):
        source = self.approved()
        project = self.project(source)
        derived = self.assets.derive_audio(source["id"], {"duration": 1})
        _, path = self.assets.verify(source["id"])
        path.write_bytes(b"Changed normalized source")
        with self.assertRaises(ValueError):
            self.engine.execute(project["run_id"])
        self.assertEqual(self.store.run(project["run_id"])["status"], "ready")
        with self.assertRaises(ValueError):
            self.assets.verify(derived["id"])

    def test_imported_visual_and_music_keep_attribution_in_real_timeline_delivery(self):
        path = self.root/"image.png"
        media.command(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", "-threads", "1", str(path)])
        image = self.assets.import_file(path, self.meta(kind="image", rights="public-domain", attribution="Original synthetic visual attribution."))
        self.assets.review(image["id"], "approve", "Visual source and credit reviewed.")
        audio = self.approved(rights="licensed", attribution="Original synthetic audio attribution.")
        timeline = Timeline(self.store)
        spec = {"title": "Imported media edit", "width": 640, "height": 360, "shots": [{"id": "one", "source": {"asset": image["id"]}, "duration": 0.5}], "music": {"source": {"asset": audio["id"]}, "gain": 0.15}}
        timeline.create("edit", spec)
        timeline.review_shot("edit", "one", 1, "approve", "Frame, sound and credits reviewed.")
        timeline.seal("edit", 1); timeline.render("edit", 1); timeline.approve("edit", 1)
        with zipfile.ZipFile(io.BytesIO(timeline.bundle("edit"))) as archive:
            manifest = json.loads(archive.read("timeline.json"))
            self.assertEqual(len(manifest["credits"]), 2)
            self.assertEqual({c["attribution"] for c in manifest["credits"]}, {"Original synthetic visual attribution.", "Original synthetic audio attribution."})
            self.assertNotIn("rights_note", archive.read("timeline.json").decode())
