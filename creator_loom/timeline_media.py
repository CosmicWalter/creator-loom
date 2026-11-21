"""Bounded local FFmpeg edits; filters are built from validated values only."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

MAX_BYTES = 128 * 1024 * 1024


def command(args, directory=None, timeout=120):
    try:
        result = subprocess.run(args, cwd=directory, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Local media tool unavailable or timed out; no remote operation was submitted") from None
    if result.returncode:
        # Never return FFmpeg stderr: it can contain local paths or source tags.
        raise ValueError("Local media processing failed; inspect the selected media privately")
    return result.stdout


def probe(path):
    args = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                   "-format_whitelist", "png_pipe,ppm_pipe,wav,mov", "-show_entries",
                   "stream=codec_type,codec_name,width,height,sample_rate,channels,duration:format=duration",
                   "-of", "json"]
    if Path(path).suffix == ".mp4":
        args += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    raw = command(args+[str(path)], timeout=20)
    value = json.loads(raw)
    if not isinstance(value.get("streams"), list) or not value["streams"]:
        raise ValueError("Source has no supported media streams")
    for stream in value["streams"]:
        if stream["codec_type"] == "video":
            if not all(type(stream.get(k)) is int and 16 <= stream[k] <= 8192 for k in ["width", "height"]):
                raise ValueError("Source image/video dimensions exceed the supported bounds")
        if stream["codec_type"] == "audio":
            if stream.get("channels") not in {1, 2} or not 8000 <= int(stream.get("sample_rate", 0)) <= 192000:
                raise ValueError("Source audio must be mono/stereo, 8–192 kHz")
    return value


def duration(info, kind):
    stream = next((s for s in info["streams"] if s["codec_type"] == kind), None)
    if stream is None:
        raise ValueError("Source does not contain the requested media type")
    value = float(stream.get("duration", info.get("format", {}).get("duration", 0)))
    if not math.isfinite(value) or not 0 < value <= 3600:
        raise ValueError("Source duration must be positive and at most one hour")
    return value


def srt(captions):
    def stamp(value):
        millis = round(value*1000)
        seconds, ms = divmod(millis, 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minute = divmod(minutes, 60)
        return f"{hours:02d}:{minute:02d}:{sec:02d},{ms:03d}"
    return "\n\n".join(f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}"
                        for i, c in enumerate(captions, 1)) + ("\n" if captions else "")


def render(spec, sources, directory):
    """Render into a fresh private directory; callers publish only after validation."""
    directory = Path(directory)
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    base = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-filter_threads", "1", "-filter_complex_threads", "1"]
    names = []
    for index, shot in enumerate(spec["shots"]):
        name = f"shot-{index:04d}.mp4"
        frames = round(shot["duration"]*fps)
        path = sources[shot["source"]["sha256"]]
        image = path.suffix in {".png", ".ppm"}
        args = base + ["-protocol_whitelist", "file,pipe", "-format_whitelist", "png_pipe,ppm_pipe,image2,mov"]
        if image:
            args += ["-loop", "1", "-framerate", str(fps)]
        else:
            args += ["-enable_drefs", "0", "-use_absolute_path", "0", "-ss", str(shot["in"])]
        args += ["-i", str(path)]
        vf = f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        if shot["motion"] == "zoom-in":
            vf = (f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,crop={width*2}:{height*2},"
                  f"zoompan=z='1+0.08*on/{max(frames-1, 1)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
                  f"d=1:s={width}x{height}:fps={fps},setsar=1")
        args += ["-map", "0:v:0", "-an", "-sn", "-vf", vf, "-frames:v", str(frames),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "2",
                 "-map_metadata", "-1", "-map_chapters", "-1", "-fs", str(MAX_BYTES), name]
        command(args, directory, timeout=180)
        info = probe(directory/name)
        if abs(duration(info, "video")-shot["duration"]) > 1/fps+0.005:
            raise ValueError("Rendered shot duration differs from the frozen edit")
        names.append(name)
    (directory/"cuts.txt").write_text("".join(f"file '{name}'\n" for name in names))
    args = base + ["-protocol_whitelist", "file,pipe", "-f", "concat", "-safe", "1", "-i", "cuts.txt"]
    audio_filters, audio_inputs = [], []
    for role in ["narration", "music"]:
        track = spec[role]
        if track is None:
            continue
        index = len(audio_inputs)+1
        if track["loop"]:
            args += ["-stream_loop", "-1"]
        args += ["-protocol_whitelist", "file,pipe", "-format_whitelist", "wav", "-ss", str(track["in"]), "-i", str(sources[track["source"]["sha256"]])]
        label = f"track{index}"
        audio_filters.append(f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                             f"volume={track['gain']},apad,atrim=duration={spec['duration']}[{label}]")
        audio_inputs.append(f"[{label}]")
    if audio_inputs:
        audio_filters.append("".join(audio_inputs)+f"amix=inputs={len(audio_inputs)}:normalize=0,alimiter=limit=0.95:latency=1[mix]")
        args += ["-filter_complex", ";".join(audio_filters)]
    captions = spec["captions"]
    if captions:
        (directory/"captions.srt").write_text(srt(captions), encoding="utf-8")
        subtitle_index = len(audio_inputs)+1
        args += ["-protocol_whitelist", "file,pipe", "-f", "srt", "-i", "captions.srt"]
    args += ["-map", "0:v:0", "-c:v", "copy"]
    if audio_inputs:
        args += ["-map", "[mix]", "-c:a", "aac", "-b:a", "192k"]
    if captions:
        args += ["-map", f"{subtitle_index}:s:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=und"]
    args += ["-t", str(spec["duration"]), "-map_metadata", "-1", "-map_chapters", "-1", "-metadata", "title=",
             "-metadata", "artist=", "-metadata", "comment=", "-movflags", "+faststart", "-fs", str(MAX_BYTES), "film.mp4"]
    command(args, directory, timeout=240)
    info = probe(directory/"film.mp4")
    if abs(duration(info, "video")-spec["duration"]) > 1/fps+0.005:
        raise ValueError("Final film duration differs from the frozen timeline")
    kinds = {s["codec_type"] for s in info["streams"]}
    if (bool(audio_inputs) != ("audio" in kinds)) or (bool(captions) != ("subtitle" in kinds)):
        raise ValueError("Final film is missing a requested media track")
    return ["film.mp4"] + (["captions.srt"] if captions else [])
