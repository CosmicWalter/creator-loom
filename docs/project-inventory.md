# Existing creation workflows and migration boundaries

Local workflow documentation was inspected before creating this repository. No source code, model weights, media assets, private deployment instructions, credentials or user databases from those projects are included here. Names below identify workflows, not publicly available dependencies. Their functionality has not been independently revalidated as part of this prototype.

| Workflow | Observed experience | Current implementation here | Further migration |
| --- | --- | --- | --- |
| Bookcast Studio | Authorized book import, episode splitting, queued speech and cover videos | TXT/EPUB chapter units → reviewed series → narration/speech/static-image videos | Rich episode timeline, durable remote job IDs |
| Talkshow | Rewriting, voice references, concurrent queues, subtitle timing, platform receipts | Spoken-script recipe and explicit review | Voice authorization, timing, delivery bundles, publishing adapters |
| Meme Studio | Source discovery, asset approval, leased downloads, manual generative-video handoff | Caption → image recipe only | Rights-aware asset library, clip editing, verified video providers |
| Cover / AIGC | Character references, reference consistency, short sample gates, stop-motion composition | SVG/PPM cover, image endpoint contract | Reference-conditioned image adapters, shot reviews, stop-motion timeline |
| Cutbot | Media assembly, account-separated queues and publication safety | Reviewed multi-shot FFmpeg cuts, image zoom, explicit subtitles and two-track mixing | Automatic shot selection, direct-manipulation multi-track editing and explicit publishing |
| NovelForge | Chapter rewrite, translation, human review, platform draft boundaries | Imported chapter → adaptation outline → prose, with reviewed continuity and versioned cited character facts | Model-quality validation of continuity proposals, semantic contradiction reasoning and publishing drafts |
| Suno adaptation | Documentation describes fixed audio/lyrics, independent vs tape audio processing, controlled variants and explicit manual Cover handoff; actual generation was not validated | Authorized imports, reproducible reference edits, routed lyric/direction plans, manual handoff and locally reviewed result adoption | Live provider receipts, phonetic assistance and independently scored multi-take listening |
| MediaFlow | Immutable workflow snapshots, artifact hashes, submit-once inference | Narration adapter, frozen segment jobs, resumable polling, explicit reconciliation | Transcription delivery and richer workflow adapters |
| OmniPublish | One upload, existing authenticated accounts, per-platform receipt | No publishing integration yet | Isolated connector; final approval and remote receipt required |

The reusable lesson is separation of creative intent, execution, identity, review, and delivery. Migration must keep those boundaries rather than copy a private application's deployment assumptions. Any future code reuse requires a file-level license and ownership review; original third-party attribution must remain intact.
