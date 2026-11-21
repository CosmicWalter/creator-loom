# Authorized media and music workflow

Creator Loom can prepare a music brief, process an authorized reference, and preserve a reviewed manual handoff/result trail. The new `song` recipe produces **lyric and musical-direction text only**. It does not analyze audio, generate a song, log into Suno, press Create/Download, select A/B, or publish anything. Existing connected Studio capabilities were not a public generation API for this application, so no undocumented API is invented here.

The local Suno research documentation informed fixed-input/provenance and independent-vs-tape processing boundaries. No private source code, credentials, songs, presets or deployment configuration were imported. Examples and tests use original synthetic content. Neither those tests nor text model priors establish Suno output quality.

## Import and review sources

Use **素材与音乐** in the local workbench, or the CLI:

```sh
loom asset-import reference.wav --metadata metadata.local.json --key original-reference
loom asset-inspect ASSET_ID
loom asset-review ASSET_ID --decision approve --note 'Listened to the actual file and checked rights and credits.'
```

Copy [the metadata template](../examples/media-metadata.json), fill the title, kind, source rights, private rights note and public attribution, then explicitly set `authorized` true after checking them. The template is deliberately not pre-authorized. Permission for possession is not automatically permission for adaptation, uploading, redistribution or commercial use.

Browser uploads allow 32 MB; CLI inputs allow 64 MB. Audio/video are bounded to ten minutes and visual dimensions to 16–4096 pixels. Accepted inputs are PNG/JPEG images, WAV/MP3 audio and MP4 video. Imports normalize to PNG, 48 kHz stereo PCM WAV or silent H.264 MP4; video source audio is not retained. Import audio separately when needed. Supported media codecs still depend on installed FFmpeg/FFprobe.

Original bytes remain privately in the chosen data directory under `source.bin`. Normalized files use generic names, with original/normalized hashes and no original filename/path metadata. Inherited FFmpeg/container tags are removed, but content and format-specific metadata still require inspection; this is not an anonymity guarantee. Invalid/failed imports do not become approved assets. Stable request keys bind content and declared rights rather than duplicating an import on retry.

Only approved sources can be reused. Approval/rejection is immutable; new material or corrected rights requires another import. Licensed and public-domain sources need explicit public attribution. The approved asset ZIP includes the normalized file and public credits. Private rights notes, operator origin links, raw source bytes and device paths stay out of export. Timelines and music handoffs preserve the public credits instead of stripping them.

## Prepare a reproducible reference

Approved audio can be trimmed and processed as another asset:

```sh
loom asset-derive ASSET_ID --settings edit.local.json --key reference-edit
```

Settings example:

```json
{"start": 0, "duration": 20, "tempo": 0.9, "semitones": 2, "mode": "independent"}
```

`duration` means input duration, so slower output becomes longer. Independent mode changes pitch in semitones (−12 to +12) and speed (0.5–2) separately. Tape mode couples speed and pitch and requires `semitones: 0` (no second independent pitch setting). Output is limited to ten minutes. Every result retains its parent hash, public credits and numeric settings and needs a fresh listening review; a missing/changed parent blocks reuse. Derivation chains are bounded to 16 references.

The processing uses FFmpeg resampling and tempo filters; it is not a new arrangement or a claim of studio-quality pitch correction. Review artifacts and actual duration before using them as a reference.

## Route a lyric/direction plan

Copy [the original brief template](../examples/music-brief.json), declare the actual adaptation authorization, and optionally add `"source": {"asset":"APPROVED_AUDIO_ID"}`. Private authorization notes are stored locally, separate from prompts. `lyrics_rights`, `lyrics_attribution` and `lyrics_license_url` declare the lyric source separately; licensed/public-domain lyrics need public attribution. Lyric/reference credits accompany handoff and must be preserved in the adopted result asset.

```sh
loom --config config.local.json music-new quiet-lantern --spec music.local.json --key quiet-lantern-plan
loom music-inspect quiet-lantern
# Inspect the reserved run's frozen plan before explicit execution.
loom inspect RUN_ID
loom execute RUN_ID
loom approve RUN_ID
```

The plan binds approved source hashes and allocates models separately for `song:lyrics` and `song:direction`, under the existing privacy/input/budget/latency constraints. Only title, intent and authorized lyric text are used as creative source data by those text steps. Bound reference audio is retained for the operator and is **not sent to or heard by the text model**. Private rights notes are not included in the text brief. Missing/changed audio provenance blocks execution/approval/handoff even though no audio inference occurs.

Read both actual outputs. Preserve intended language and section structure, check phonetics/pronunciation with a competent speaker, and distinguish proposed settings from observed results. There is no automatic Jyutping validation or live music-quality calibration in this release.

## Explicit manual handoff

```sh
loom music-handoff quiet-lantern --transfer-authorized --note 'Authorized this reviewed lyric/direction package for the intended external workflow.'
# Only when the reference itself may be transferred:
# Add --include-audio when preparing a new project's handoff.
```

The package lives under `music/PROJECT_ID/handoff.zip` inside the selected local data directory; the workbench provides a download. It contains `lyrics.md`, `direction.md` and a minimal `brief.json`. Reference WAV is excluded unless explicitly selected; its inclusion needs the same transfer authorization. ZIP timestamps are neutral. Plans, endpoints, run/asset IDs, private rights notes and provider/account origin URLs are excluded; required public source credits are included.

Handoff decisions and hashes are frozen. Different transfer decisions need a separate project. Preparing/downloading a package does not submit a remote job. The operator must choose the intended Suno operation, confirm reference, lyrics and settings, and perform the external action themselves. The application makes no generation, pricing, plan-entitlement or copyright conclusion from this local package.

## Record and adopt actual results

```sh
loom music-external quiet-lantern --reference https://suno.com/song/RESULT_ID --note 'Operator records the actual external result reference; not an API receipt.'
```

A song/share URL must use Suno HTTPS without credentials, query or fragment. The application does not fetch it, alter its visibility, or verify access/account/generation status. It remains a private operator-reported reference, not proof of provider completion or publication.

Import the audio you are authorized to use, declaring `origin.service: "suno"` and the same `origin.reference` URL. Listen to the normalized file and approve it. Then:

```sh
loom music-attach quiet-lantern --asset RESULT_ASSET_ID --note 'Compared the local result with the brief and adopted this reviewed take.'
```

Adoption requires matching declared origin and an approved, hash-verified local audio asset. It proves those local conditions, not that Suno generated that audio. The adopted asset can be selected as narration/music in the editing room. Another take requires another retained project/attempt, rather than silently replacing the adopted result.

## Evidence still missing

Tests use original synthetic frames/tones, real FFmpeg and simulated text inference. They cover import bounds, metadata handling, public attribution, decoded pitch/tempo/duration, immutable review, plan/source integrity, manual package gates, matching reported origins and actual local delivery. They do not establish live Suno compatibility, real remote receipts, provider billing, generated song quality, reliable phonetic conversion or browser/visual acceptance. Those remain separate roadmap work.
