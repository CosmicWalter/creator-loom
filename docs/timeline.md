# Reviewed local timeline

The CLI timeline turns approved creative artifacts into an editable multi-shot film. It supports cuts between still images or video clips, center zoom on still images, one narration track, an optional music track, and explicit selectable subtitles. It runs locally with FFmpeg/FFprobe; it does not call a generative-video model.

## Prepare sources and an edit

Use normal creation recipes, inspect the actual artifacts, and approve the source runs. Inspect each run to obtain its step ID and artifact `file` value. Only reviewed PNG/PPM images, MP4 video and PCM-compatible WAV audio are accepted; raw file paths, network URLs and unreviewed outputs are rejected. This release reuses creation artifacts rather than importing arbitrary external media. Confirm rights to the content and music before reuse.

Start from [the edit template](../examples/timeline.json). Replace its source references with actual approved run IDs and artifact names. The template contains placeholders and is not a runnable demonstration without those sources.

```sh
loom timeline-new reading-film --spec edit.local.json
loom timeline-inspect reading-film
```

A shot has an ID, source reference, duration, optional `in` point and optional `motion`. Source hashes are frozen during creation. Durations must fall on exact frame boundaries. Supported canvases are 1280×720, 720×1280, 640×360 and 360×640 at 24, 25 or 30 fps. An edit has 1–120 shots, each 0.25–120 seconds, with at most ten minutes total duration.

`still` preserves the full visual inside a padded canvas; `zoom-in` fills and crops a still image to the canvas, then zooms toward its center by 8%. Video shots use `in` and duration to trim the source; zoom motion is currently limited to still images. Cuts are direct; there are no transitions, compositing layers or automatic shot selection yet.

## Review shots and render

Review each shot's selected source, framing, crop, timing and relationship to the narration. Decisions cannot be overwritten; rejected shots require a revised edit.

```sh
loom timeline-shot reading-film opening --base-version 1 --decision approve --note 'Reviewed source, framing, timing and rights.'
loom timeline-shot reading-film closing --base-version 1 --decision approve --note 'Reviewed the crop and its relation to the narration.'
loom timeline-seal reading-film --base-version 1
loom timeline-render reading-film --base-version 1
```

Every source is rechecked before review, sealing and rendering, and again after rendering. All shots must be approved before sealing. The local output remains `needs_review` until the final film is approved. Rendering uses an OS lock; a duplicate completed render returns existing output rather than rerunning. Failed or interrupted work retains its source references and requires a new revision. Nothing is automatically submitted to external providers.

## Sound and captions

Narration and music each select an approved WAV. `gain` ranges from 0 to 2; the default is 1 for narration and 0.15 for music. Both tracks are resampled to 48 kHz stereo and mixed with a limiter. Short narration is padded with silence; audio longer than the edit is trimmed. Music can loop only when its `in` point is zero. Clip source audio is deliberately omitted: only the explicit narration and music tracks are mixed. There is no automatic ducking or loudness normalization.

Captions specify `start`, `end` and plain `text`, in ordered, non-overlapping seconds within the edit. The renderer delivers UTF-8 SRT and a selectable MP4 subtitle track. Captions are not burned into the picture. Timing is provided by the editor; there is no speech recognition, forced alignment or word-level synchronization in this feature. Caption rendering and fonts depend on the playback application.

## Revise and deliver

Edit the JSON spec and save it as a new version:

```sh
loom timeline-revise reading-film --spec revised.local.json --base-version 1
loom timeline-inspect reading-film --version 1
```

The previous version's spec, review decisions and output remain available. New revisions reset shot reviews. Stale version arguments are rejected. The normalized `spec` returned by inspect can be reused; if shot durations change, remove or update its derived `duration` field.

Review the actual film and subtitle files in the local timeline output directory, then:

```sh
loom timeline-approve reading-film --base-version 2
loom timeline-export reading-film --version 2
```

Export requires final approval and verifies both source and output hashes. The ZIP contains only `film.mp4`, `timeline.json` and, if requested, `captions.srt`. Its edit manifest includes creative settings and source content hashes, excluding source paths, run IDs, provider settings and operational records. Archives use neutral timestamps and source container metadata is not copied to the rendered film. Content itself still needs review for privacy, licensing and accuracy before sharing. Export does not publish or upload anything.

## Verification and limits

Tests use original synthetic images and sine-wave audio with actual FFmpeg: cuts are checked by decoded frame colors, zoom by changing decoded frames, audio mixing and looping by decoded frequencies, captions by actual stream presence, and source tags by inspection of the final container. Model inference is simulated; this is media execution evidence, not creative-quality evidence. A workbench timeline editor and browser/visual acceptance are still pending.
