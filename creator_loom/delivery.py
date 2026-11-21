"""Reviewed deliverables only; never export execution credentials or raw plans."""

import hashlib
import io
import json
import math
import zipfile

from .assets import Assets


def delivery(engine, run_id):
    run = engine.store.run(run_id)
    if run["status"] != "approved":
        raise ValueError("Approve the actual artifacts before creating a delivery bundle")
    engine.verify_artifacts(run)
    buffer = io.BytesIO()
    entries, total = [], 0
    deliverable_names = {"content.md", "image.png", "narration.wav", "film.mp4", "cover.ppm", "cover.svg", "timings.json"}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        def write(name, data):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)

        for step in run["steps"]:
            for result in [step["result"], *step["result"]["supplements"]]:
                path = engine.artifact(run_id, result)
                if path.name not in deliverable_names:
                    continue
                raw = path.read_bytes()
                if path.name == "timings.json":
                    original = json.loads(raw)
                    cues = []
                    for cue in original["segments"]:
                        start, end, text = cue["start"], cue["end"], cue["text"]
                        if not all(type(x) in {float, int} and math.isfinite(x) for x in [start, end]) or not isinstance(text, str):
                            raise ValueError("Invalid timing data")
                        cues.append({"start": start, "end": end, "text": text})
                    raw = json.dumps({"alignment": "segment durations", "segments": cues}, ensure_ascii=False, indent=2).encode()
                total += len(raw)
                if total > 128 * 1024 * 1024:
                    raise ValueError("Delivery bundle exceeds the 128 MB content limit")
                name = step["id"] + "/" + path.name
                write(name, raw)
                entries.append({"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        manifest = {"schema": 1, "generator": "Creator Loom", "format": run["brief"]["format"],
                    "language": run["brief"]["language"], "files": entries,
                    "isolated_task": run["plan"].get("isolated_task"),
                    "credits": list(run["plan"].get("public_credits", [])) + [Assets(engine.store).credits(ref["asset"]) for ref in run["plan"].get("input_assets", [])]}
        write("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buffer.getvalue()
