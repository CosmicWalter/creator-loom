# Reviewed local timeline

The CLI timeline turns approved creative artifacts into an editable multi-shot film. It supports cuts between still images or video clips, center zoom on still images, one narration track, an optional music track, and explicit selectable subtitles. It runs locally with FFmpeg/FFprobe; it does not call a generative-video model.

For a form-based editor, run `loom serve --open` and choose **剪辑台**. The same version/review/render constraints apply. The CLI below remains useful for reproducible edit files.

## Prepare sources and an edit

Use normal creation recipes, inspect the actual artifacts, and approve the source runs. Inspect each run to obtain its step ID and artifact `file` value. Reviewed creation artifacts or explicitly imported and approved media can be selected. Raw filesystem paths, network URLs and unreviewed assets cannot be used as timeline references. Imports normalize PNG/JPEG to PNG, WAV/MP3 to PCM WAV, and MP4 to silent H.264 MP4; see [music and media](music.md). Confirm rights to the content and music before reuse.

Start from [the edit template](../examples/timeline.json). Replace its source references with actual approved run IDs and artifact names. The template contains placeholders and is not a runnable demonstration without those sources.

```sh
loom timeline-new reading-film --spec edit.local.json
loom timeline-inspect reading-film
```

A shot has an ID, source reference, duration, optional `in` point and optional `motion`. Source hashes are frozen during creation. An imported source uses `{"asset":"APPROVED_ASSET_ID"}`; the planner freezes its hash and kind. Public attribution/license fields are carried into the delivered edit manifest, while private rights notes and origin links remain local. Durations must fall on exact frame boundaries. Supported canvases are 1280×720, 720×1280, 640×360 and 360×640 at 24, 25 or 30 fps. An edit has 1–120 shots, each 0.25–120 seconds, with at most ten minutes total duration.

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

Narration and music each select an approved WAV. `gain` ranges from 0 to 2; the default is 1 for narration and 0.15 for music. Both tracks are resampled to 48 kHz stereo and mixed with a limiter. Short narration is padded with silence; audio longer than the edit is trimmed. Music can loop only when its `in` point is zero. Clip source audio is deliberately omitted: only the explicit narration and music tracks are mixed. Music can opt in to `"ducking": true` (default off). It requires a selected narration track with nonzero gain. The renderer uses post-gain narration as the control signal to compress only music, then mixes the unchanged narration and ducked music through the existing limiter. When narration becomes quiet or ends, music gradually recovers. The workbench exposes the switch and shows the saved setting during review; the exported edit manifest preserves it. Changing the switch creates another edit version and resets reviews, as with other sound edits.

The fixed sidechain settings are a linear RMS threshold of 0.015625 (about −36 dBFS), 8:1 ratio, 20 ms attack, 350 ms release, soft knee 2.828427, average stereo linking and unity makeup. This is signal-level ducking: quiet speech below the threshold may not reduce music, while noise or other sounds in the narration can trigger it. The music gain remains the upper level; very quiet tracks may stay quiet after recovery. It does not identify speech, align subtitles, normalize loudness or guarantee intelligibility. Listen to the actual output before approval. Existing saved edits without the option retain their original fixed-gain mix.

For example, add the option to a selected approved music reference:

```json
{"source":{"asset":"APPROVED_MUSIC_ASSET"},"gain":0.3,"loop":true,"ducking":true}
```

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

Tests use original synthetic images and sine-wave audio with actual FFmpeg: cuts are checked by decoded frame colors, zoom by changing decoded frames, audio mixing and looping by decoded frequencies, optional ducking by comparing decoded music/voice frequencies against a fixed-gain control and checking recovery after narration ends, captions by actual stream presence, and source tags by inspection of the final container. Model inference is simulated; this is media execution evidence, not creative-quality evidence. The workbench now exposes source selection, shot/timing/sound/caption editing, review, rendering and delivery; see [the editing room](workbench.md#editing-room). HTTP/media execution is verified; browser/visual acceptance remains pending.
