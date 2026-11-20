# Optional MediaFlow narration and recovery

Creator Loom consumes an independently running local MediaFlow API. The client was implemented against the inspected API contract; no private application code, settings, account data or model weights are included. A standard OpenAI-compatible speech provider remains available without MediaFlow.

## Contract and model card

The observed service provides `POST /api/assets`, idempotent `POST /api/jobs`, `GET /api/jobs/ID` and repeatable `GET /api/jobs/ID/files/speech.wav`. A TTS job contains `kind: "tts"`, the uploaded voice `source_id`, text, optional reference `prompt_text`, and `voice_authorized: true`. It returns a 32-character lowercase hexadecimal job ID and persisted request parameters. The service's current engine is IndexTTS; this adapter does not switch its loaded model.

```sh
loom mediaflow-upload-voice reference.wav --endpoint http://127.0.0.1:18120 --voice-authorized
```

Upload requires an explicit authorization declaration and a nonempty PCM WAV of at most 10 MB / 30 seconds. It is named `reference.wav` in the HTTP upload, without the original local filename or path. An interrupted upload may leave an unreferenced asset, but it does not submit inference. The authorization flag is an operator assertion, not independent proof of voice ownership.

Copy the example `mediaflow-local` card to local configuration, replace its placeholder `voice` with the returned asset ID, set `voice_authorized` to true and enable it. Required values are `adapter: "mediaflow"`, `capability: "audio"`, `model: "indextts"`, `local: true`, and a loopback root endpoint. Credential environment variables and non-loopback endpoints are rejected. Optional `voice_prompt` is the reference transcript (up to 1000 characters); `segment_chars` is 20–500, default 150. Narration input is capped at 15000 characters, further constrained by the card's `max_chars`.

Requests bypass environment proxies, reject redirects, and use no browser sessions or saved account credentials. The endpoint's own downstream engine may still be remote or tunneled; loopback routing alone does not certify where inference happens.

## Segmentation, output and cost

Narration text splits near paragraph/sentence boundaries, or at a hard character bound. All segment requests and independent idempotency keys are frozen before the first inference submission. Segments execute sequentially; a completed cached segment is verified before reuse. PCM sample rate, channel count and sample width must match across segments. The combined output is capped at 32 MB.

The resulting `narration.wav` is accompanied by `timings.json` and a remote-job manifest. Timings use each segment's actual audio duration, not word-level alignment or recognized subtitle timing. A bookcast/talkshow workflow can continue from the assembled narration to its existing static-image video renderer. This version does not burn these timings as subtitles.

The card's `cost` remains a configured estimate for the complete narration step; there is no verified provider bill or per-segment monetary accounting here. Completed-step wall time includes queue, polling and operator delays, so it is not a clean inference-speed measurement. Waiting steps have no final measurement row yet.

## Execute, resume and wait

```sh
loom --config config.local.json execute RUN_ID
loom remote-ops RUN_ID
loom resume RUN_ID
loom wait RUN_ID --timeout 300 --interval 2
```

`waiting_external` is a saved checkpoint, not delivery completion. `resume` advances it once. `wait` repeats safe checkpoint advancement in the foreground until review, reconciliation, failure or its waiting timeout. A network operation may finish after the wait deadline. Stopping this command does not cancel remote work.

Resume verifies source and completed artifact hashes, skips completed writing/cover work, queries known tasks and downloads their persisted files. Once a segment succeeds it can submit the **next already planned segment**; it is not restricted to GET-only work across the entire workflow. It never creates a replacement for a known failed/interrupted task, calls the service's resume endpoint, or automatically approves its review gates.

An OS execution lock prevents two local processes from advancing the same run concurrently. Its file may remain after exit; only the live descriptor lock represents ownership. If a process died in an asynchronous checkpoint, `resume` can recover it once the lock is available. A synchronous step marked running is not automatically replayed. If every artifact was saved before a final-state crash, resume only verifies and finalizes it without network calls.

## Unknown submission receipts

Submission intent is committed before POST. If the response is lost, malformed or unverified, the segment remains `unknown` (or `submitting` after a crash). Neither `resume` nor `wait` sends that POST again, even with the same key. Inspect the service and identify the existing task:

```sh
loom remote-ops RUN_ID
loom mediaflow-reconcile RUN_ID narration SEGMENT_INDEX REMOTE_JOB_ID
loom resume RUN_ID
```

Reconciliation only GETs the specified task and verifies its kind, source asset, text, reference transcript and authorization against the frozen segment request. It rejects a different task or a task already assigned to another segment. Binding does not submit new inference and does not make a failed task successful. If there is no verifiable receipt, retain the unknown attempt and resolve it manually; the client offers no automatic retry override.

The backend must retain its task and idempotency database. Restoring/replacing a server at the same URL is outside a cross-system exactly-once guarantee. Do not discard local receipts to force a new inference. `forget` retains them; they belong to execution history, not personalization.

## Validation

Unit/integration tests use actual loopback HTTP with a simulated MediaFlow service. They exercise known-ID polling, lost POST responses, download interruption, incompatible/changed inputs, failed tasks, true process locks, final checkpoint recovery and actual FFmpeg continuation.

With a separate MediaFlow checkout/environment, the optional script starts an isolated real API/worker, synthetic reference audio and a deliberately simulated IndexTTS engine:

```sh
python scripts/validate_mediaflow.py --mediaflow-source ../mediaflow \
  --mediaflow-python ../mediaflow/.venv/bin/python
```

It uses temporary databases and new loopback listeners only, then terminates its own processes. The verified run drafted once, submitted two inference segments once each, consumed each upstream result once and produced a reviewed real FFmpeg video. This validates service integration and recovery mechanics. It does not validate actual model loading, human speech, voice similarity, audio quality or creative quality.
