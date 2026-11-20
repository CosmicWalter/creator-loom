# Existing creation workflows and migration boundaries

Local workflow documentation was inspected before creating this repository. No source code, model weights, media assets, private deployment instructions, credentials or user databases from those projects are included here. Names below identify workflows, not publicly available dependencies. Their functionality has not been independently revalidated as part of this prototype.

| Workflow | Observed experience | Current implementation here | Further migration |
| --- | --- | --- | --- |
| Bookcast Studio | Authorized book import, episode splitting, queued speech and cover videos | Narration → speech → static-image video recipe | Chapter import, episode timeline, durable remote job IDs |
| Talkshow | Rewriting, voice references, concurrent queues, subtitle timing, platform receipts | Spoken-script recipe and explicit review | Voice authorization, timing, delivery bundles, publishing adapters |
| Meme Studio | Source discovery, asset approval, leased downloads, manual generative-video handoff | Caption → image recipe only | Rights-aware asset library, clip editing, verified video providers |
| Cover / AIGC | Character references, reference consistency, short sample gates, stop-motion composition | SVG/PPM cover, image endpoint contract | Reference-conditioned image adapters, shot reviews, stop-motion timeline |
| Cutbot | Media assembly, account-separated queues and publication safety | Real local FFmpeg composition | Clip selection, captions, audio mixing, optional explicit publishing |
| NovelForge | Chapter rewrite, translation, human review, platform draft boundaries | Outline → opening chapter | Chapter memory, provenance, import and export |
| MediaFlow | Immutable workflow snapshots, artifact hashes, submit-once inference | Plan snapshots, hashes and conservative no-replay state | Verified adapter to existing job API, resumable polling |
| OmniPublish | One upload, existing authenticated accounts, per-platform receipt | No publishing integration yet | Isolated connector; final approval and remote receipt required |

The reusable lesson is separation of creative intent, execution, identity, review, and delivery. Migration must keep those boundaries rather than copy a private application's deployment assumptions. Any future code reuse requires a file-level license and ownership review; original third-party attribution must remain intact.
