# Changelog

## 0.8.0

- Add CLI task-isolated model comparisons with frozen plans, preassigned development/holdout briefs and randomized A/B presentation. Candidate targets reuse the baseline's exact upstream artifacts.
- Lock holdout generation until immutable development reviews are sealed. Protect ordinary execution and feedback paths from bypassing the benchmark protocol.
- Export minimal reviewer packets with shared creative inputs, excluding model/run mappings and operational sidecars. Local owners can still inspect mappings; generated content may reveal identity.
- Report separate partition outcomes and descriptive sign-test results. Explicit calibration uses only approved, hash-verified holdout artifacts and task/backend-scoped quality feedback.
- Add synthetic protocol tests. No live-provider quality evidence, independent reviewer validation or equal-spend comparison is claimed.

## 0.7.0

- Add a dependency-free, authenticated loopback workbench for creation, archives, books/series, research review and creator practice. It reads actual persisted state, without fabricated dashboard metrics.
- Freeze previewed plans before confirmation; persist idempotent creation/action keys and do not replay interrupted background actions on server restart.
- Preview hash-verified text, image, audio and video artifacts with range support. Retain existing explicit execution, asynchronous recovery and review gates.
- Export only reviewed deliverables through an allowlist, excluding execution receipts and provider usage sidecars. Sanitize timing fields and use neutral archive timestamps with content hashes.
- Add real HTTP workbench flows and boundary checks, plus wheel asset checks. Browser interaction and visual acceptance remain pending in this release.

## 0.6.0

- Add optional local MediaFlow narration with explicit reference-voice authorization, bounded uploads, segmented requests, durable task IDs and validated PCM assembly/timings.
- Persist submission intent before POST; unknown receipts require explicit binding to a matching existing job, never automatic resubmission. Known tasks use safe status/file GETs.
- Add process-lifetime execution locks, selective MediaFlow resume, bounded foreground waiting and recovery of fully saved completion checkpoints. Completed upstream work is verified and reused.
- Preserve asynchronous receipts during personalization resets and require explicit provider checks before rejecting externally waiting series attempts.
- Add real HTTP fault tests and a reusable isolated real-MediaFlow/real-FFmpeg validation script with simulated inference.

## 0.5.0

- Persist public RSS/Atom subscriptions, polling intervals, source versions and short fetch leases; collect due sources once or through an explicitly started foreground worker.
- Deduplicate canonical evidence links across sources, retain distinct metadata revisions, preserve review decisions and expose stale reviews after material changes.
- Rank inbox entries through explained literal keyword matches, with explicit dismissal/reopening and optimistic review revisions.
- Atomically turn reviewed evidence into a proposed editorial technique, freezing the source snapshot and human rationale. Existing paired evaluation, activation and rollback gates still apply.
- Harden feed parsing, public URLs, body limits, redirects and error retention. Add explicit system curl transport for native CA trust without disabling TLS or inheriting user curl configuration.

## 0.4.0

- Import explicitly authorized TXT and unencrypted EPUB sources, preserve original/source-unit hashes and split long chapters into bounded units without copying local filenames or source paths.
- Adapt individual source units through existing multimodal recipes; freeze original text, provenance and reviewed continuity in each plan.
- Add sequential series creation with atomic pending-run reservation, idempotent next calls, artifact-bound acceptance and optimistic continuity versions.
- Keep rejected attempts and source position, cancel unexecuted plans, and require explicit provider reconciliation before detaching uncertain attempts. Running episodes cannot be detached.
- Include source/continuity in paired technique comparisons and recheck provenance during promotion.
- Add original example fiction and real HTTP/two-video series integration coverage using simulated inference and actual FFmpeg.

## 0.3.0

- Route by format/stage quality priors, isolated feedback and backend/generation signatures. A novel outline and chapter can select different specialists.
- Record actual adapter wall time and outcomes. Use task-specific successful runtime observations and smoothed execution reliability in future plans.
- Capture allowlisted provider-reported chat token counts; expose configured-rate cost estimates and unpriced coverage through `metrics`. Missing usage remains unknown.
- Reserve enforced upstream output character bounds against downstream input limits during joint allocation. Configure speech voice and output token limits in model cards.
- Remove measurements from future decision inputs when forgetting a profile, while documenting retained artifact/audit history.
- Update CI to official v6 action tags.

## 0.2.0

- Allocate models jointly across workflow steps under total configured cost and latency estimates. Save search method and feasible combination counts.
- Freeze model cards, preferences and active baseline in technique evaluations; recheck artifact integrity at promotion.
- Add medium-specific coaching workbooks, changed revision artifacts, explicit assessment rationales and profile progress summaries.
- Validate WAV frames, inspect narration duration before rendering and reject oversized narration instead of silently truncating it.
- Add real image HTTP contract coverage and verify rendered video/audio streams, dimensions and duration with FFprobe. Model responses in contract tests remain simulated.

## 0.1.0

- Establish seven creation recipes, explicit model cards, routing explanations and profile feedback.
- Add durable run state, conservative no-replay handling, immutable plan snapshots and artifact-bound review.
- Add public feed discovery, sourced prompt-technique proposals, paired human review, activation and rollback.
- Document existing workflow migration, primary-source product comparisons, limitations and delivery roadmap.
- Publish an independent MIT codebase under the pseudonymous project identity.
