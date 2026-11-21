# Local creation workbench

```sh
loom serve --open
loom --config config.local.json serve --port 8787 --open
```

The workbench listens only on `127.0.0.1`. The terminal displays a local URL with a random access code in its fragment. On connection, the page exchanges that code for an HttpOnly, SameSite=Strict host cookie and removes the fragment from browser history. The code is not embedded in HTML/JavaScript or stored in the repository. Restarting the server changes the code/session. Sessions last eight hours from the last successful connection.

There is no public hosting, account/tenant system or remote collaboration in this version. Local profile names group preferences and feedback; they are not permissions. Source books and research observations belong to the single local owner. The interface loads no external fonts, scripts, analytics or image services. Configured model calls and explicit research operations retain their separate network behavior.

## Creation and review

The creation page previews a brief using the existing planner. Every preview is a persisted plan snapshot with a 30-minute confirmation window. Creating a run uses that exact snapshot rather than silently replanning after model scores/preferences change. Editing the form invalidates its displayed preview. Network retries with the same creation key return the original run.

The default no-key example is a real local graphic/SVG cover, not simulated AI inference. Text, generative images, audio and narration video still require their configured providers. The displayed counts are actual recent runs, waiting reviews and enabled model/tool configurations; they are not live model health checks or creative-quality measurements.

Execution starts only when requested, through a small background task pool. The browser polls saved action status; repeated action keys do not resubmit. A workbench restart marks leftover web actions interrupted without executing them again. Existing engine locks and remote receipt/reconciliation rules remain in effect. A waiting MediaFlow run can be explicitly continued; unknown synchronous calls cannot be replayed.

Text is displayed as text, not executed Markdown/HTML. Media previews use authenticated, digest-verified artifact routes, including byte ranges for audio/video. Changed/missing artifacts block preview or approval. Review confirms the actual files locally and does not publish to social platforms.

## Books, learning and practice

The book shelf imports TXT/unencrypted EPUB with explicit source-rights declarations and an eight-megabyte upload limit. It uses generic temporary names, not the original local filename/path. Inspect source units before creating a series. Series planning and acceptance retain the existing optimistic continuity versions and artifact-bound review.

The book shelf's **角色记忆与版本** opens reviewed character facts, citations and version history for a series. The editor lets you read available source units/accepted chapter text, copy exact quotations and record fact type/text with explicit review. A pending episode locks memory edits; historical restoration saves another reviewed version and preserves old plans. These are human-maintained facts, not automated contradiction detection. See [character memory](story-memory.md).

The learning radar shows subscribed sources, literal keyword evidence and preserved review states. It can turn reviewed evidence into a proposed editorial method, but cannot bypass paired evaluation or activate it. Selected-evidence synthesis can plan a grounded suggestion and preassigned development/holdout experiment, with immutable blind scores, final artifact approval and explicit task-scoped activation/rollback. Existing manual proposal evaluation and subscription configuration also remain available through the CLI. See [research lab](research-lab.md).

Completed works offer medium-specific review questions. The browser revision editor currently supports text steps; it records an actually changed draft, dimension, before/after self-ratings and a rationale. Other media retain review questions and ordinary feedback. Growth keeps self-reported results separate from optional A/B text-revision reviews. From **成长记录**, prepare a review packet, score the anonymized version labels on the same rubric and declare whether the scores are self/external-declared. Scores are immutable; only then does the report reveal original/revised mapping. Direct shared text inputs and public credits accompany the packet; self-scores and original editing rationale do not. Changed/missing sources or revisions invalidate comparisons in the blind summary. Reviewer identity/independence is not verified, and a revision-quality delta does not establish durable skill or transfer. See [practice review](practice-review.md).

## Media and music

**素材与音乐** imports explicitly authorized PNG/JPEG images, WAV/MP3 audio and MP4 video, with a 32 MB browser limit (64 MB via CLI). Original bytes stay in local data storage under a generic name; local filenames and device paths are not persisted. FFmpeg normalizes the media and removes inherited container metadata. Review actual content, rights, privacy and required attribution before approval. Only approved assets enter timelines or music plans. Normalization does not certify anonymity, license validity or creative rights.

Private rights notes and operator origin links stay out of delivery packages. Public attribution and license fields accompany approved asset ZIPs, music handoffs and timeline edit manifests. Original video audio is omitted during video normalization; audio must be imported/selected explicitly as an audio asset. Deleting a preference profile does not erase assets, music projects or their review/provenance records.

Approved audio offers reproducible reference edits: bounded input trim, independent speed/pitch or tape-style linked speed/pitch. Every derived file records its parent and settings, inherits credits and requires another review. This is audio processing, not generative rearrangement.

A music project reserves a normal, inspectable lyric/direction run under model constraints. Explicitly execute and approve that run before handoff. Text models receive the title, intent and authorized lyrics; the bound reference audio and private rights note are not sent to those models. Only an explicit transfer decision prepares a local handoff ZIP, and audio is excluded unless separately selected. Nothing is submitted to Suno by this application.

External song/share links and notes are operator reports. They do not verify provider execution, account identity, availability, billing or ownership. To adopt a result, import authorized audio with the same reported Suno origin, review the actual file, then bind it to the project. This verifies the local artifact/hash/review and matching declaration, not a provider receipt. See [music workflow](music.md).

## Editing room

Open **剪辑台** to select already approved images/video/WAV audio. Source choices are organized by the current preference profile and cover its most recent 300 approved runs plus 300 approved imported assets; a missing or changed source is omitted and counted. Profiles organize preferences and content, not separate users or authorization. Existing CLI timelines migrate to `default`; new CLI timelines can specify `--profile`.

Create an edit with a title, canvas and frame rate. Add shots, move them earlier/later, set duration and source-video in points, and choose still-image center zoom where appropriate. The editor aligns duration to frame boundaries. Preview is of the actual source image/clip: PPM is converted to PNG locally, not replaced with a differently typeset SVG. Final crop and motion must be checked on the rendered film.

Select narration/music from approved audio, set in points and gains, and optionally loop music from the beginning. Add ordered plain-text captions with explicit times. These are manual timings, not automatic transcription or word alignment. Original video audio is not retained unless it is an explicitly selected supported audio track.

Saving creates a frozen edit version. Inspect each shot and record approval/rejection with a reason; decisions cannot be overwritten with a different review. Once all shots are approved, seal and start local rendering. Work proceeds in the background with a persisted action key; refreshing does not resubmit it. Version-bound actions cannot silently render a newer edit, and server restart marks unfinished web actions interrupted rather than replaying them.

Inspect the actual film, use the subtitle menu for derived WebVTT captions where supported, then approve the final film before downloading its MP4/SRT/edit-manifest ZIP. Every preview, review and delivery retains source/output integrity checks. Historical versions can still be viewed and approved historical deliveries downloaded; editing from a historical version saves a new version against the current revision.

Unsaved edit fields remain in page memory when navigating within the workbench, with a resume entry in the editing room. They are not persisted across closing/reloading the page; save first. The editor requests a normal browser unload prompt when dirty, but browsers may handle that prompt differently. Failed saves retain the draft and its stable request key for retry. Browser interaction/visual acceptance is still pending.

## Deliverable bundles

An approved run can download a ZIP containing explicitly allowed creative files plus a manifest of their hashes. Raw plans, endpoints, profiles, source books, practice data, idempotency keys, remote IDs and provider usage/operational sidecars are not included. Timing JSON is rebuilt from start/end/text only. Archive entry timestamps are fixed and do not preserve the host's clock or filesystem metadata.

The bundle intentionally contains the creative work itself. It does not automatically remove private information depicted/spoken/written in content, validate rights, reconstruct required third-party attribution or scrub every media format's embedded metadata. Review the work and required credits before sharing. Download is local delivery, not public publication.

## HTTP boundary and storage

API access requires a valid local session. Host checks reject alternate/rebinding hosts, cross-origin API access is rejected, and JSON mutations require a custom request header. The public shell contains no code/session secret. Content security policies restrict script sources; artifact responses are sandboxed. HTTP request logging is disabled. Client-facing errors do not include local paths, stack traces, provider responses or credentials.

Requests are bounded; files are addressed through verified run/step slots rather than caller-selected filesystem paths. One workbench process owns a data directory at a time through an OS lock. The server is a single-user development product, not a general-purpose hardened Internet server.

Drafts, actions and run data persist in the selected data directory, which is ignored by Git. Expired previews are retained for now but cannot be confirmed. `forget PROFILE` does not erase workbench/creative/audit history. Shut down normally to let in-flight calls save their receipts; forced termination can still produce an unknown operation requiring reconciliation.

## Verification status

Real HTTP tests cover authentication, Host/Origin boundaries, frozen/idempotent creation, background cover execution, verified previews/ranges, approval/export, source import/series setup, text revision practice and blind review/export/scoring/tamper rejection, session renewal and non-replayed interrupted actions. Additional real HTTP/FFmpeg checks cover media import/review, music planning/handoff/adoption and the editing room, source preview, duplicate saves/renders, legacy profile migration, stale queued revisions, WebVTT/SRT delivery, authentication and tamper rejection. JavaScript syntax and packaged frontend assets are checked separately.

Browser interaction and visual acceptance have not yet been recorded. HTTP tests and source inspection do not establish responsive layout quality or prove that every browser interaction works. Continue that acceptance before presenting the workbench as production ready.
