# Task-aware model decisions and measurements

The planner answers a constrained, explicit question: which eligible model combination has the highest summed heuristic score for this workflow? It does not claim to identify the objectively best creative model. Provider quality and price claims are not automatically trusted.

## Model cards

`task_quality` may contain a format (`novel`) or an exact stage (`novel:outline`). Exact stage overrides format, which overrides the general `quality`. All scores are 0–1 priors configured by the operator, not benchmark results.

```json
{
  "id": "configured-writer",
  "capability": "text",
  "adapter": "chat",
  "model": "replace-with-installed-model",
  "endpoint": "http://127.0.0.1:8000/v1",
  "local": true,
  "quality": 0.6,
  "task_quality": {"novel:outline": 0.8, "novel:chapter": 0.5},
  "max_output_tokens": 2048,
  "max_output_chars": 9000,
  "max_chars": 30000,
  "cost": 0,
  "latency": 30,
  "enabled": false
}
```

Example values are illustrative. Enable only a verified endpoint/model. To estimate chat token costs, optionally provide **both** `input_price_per_million` and `output_price_per_million`; prices must use the same unit as `budget` and per-call `cost`. They are not fetched supplier prices. Cached tokens, reasoning-specific charges, tiering, discounts and invoices are not reconciled.

For speech models, `voice` is the provider's voice identifier, defaulting to `alloy`. This does not add cloning or verify voice authorization.

## Quality and scope

The unit of learning is `(profile, format:stage, backend signature)`. The signature binds model ID, adapter, capability, endpoint, model name, local designation, speech voice and output token/character settings. It excludes editable quality, cost and latency priors so recalibration does not erase history. A provider can still change the implementation behind a stable model name; pin versions when available.

MediaFlow signatures additionally bind reference-voice authorization, reference transcript and segment length. Completed MediaFlow steps report end-to-end wall time from segment reservation to assembled output, including queue/polling/operator delays; it is not isolated model inference latency. Pending checkpoints do not count as completed measurement rows. Poll promptly or use the foreground `wait` command when calibrating latency, and do not compare these samples to inference-only benchmarks.

With `n` user ratings, posterior quality is `(4 × prior + sum(ratings)) / (4 + n)`. Updating one artifact's rating replaces the prior rating rather than adding another sample. Feedback for an article does not modify novel-stage estimates. Prior-version feedback can be read from its frozen run metadata without rewriting old records.

Execution reliability is `(4 + successful_attempts) / (4 + recorded_attempts)`. Failed or uncertain attempts count against reliability; preflight failures before adapter execution do not. It measures delivery mechanics, not artistic quality. Delays after submission cannot safely be interpreted as no charge.

## Latency and input capacity

Adapter wall time includes request/response handling and artifact writing, not only supplier inference. The next latency estimate is the larger of the configured estimate and the mean of four configured-prior observations plus successful elapsed times. The allocator applies these estimates to the complete workflow's latency target. A mean is not a tail-latency or deadline guarantee.

The allocator also reserves each selected upstream writer's `max_output_chars` plus the actual prompt envelope against the selected downstream model's `max_chars`. Speech receives the narration text alone. The text adapter enforces the declared output character bound; violating output is not silently truncated. Such a response may already have incurred a charge, so the run becomes uncertain and is not replayed.

Joint allocation is exhaustive up to one million combinations. All steps share the same budget/latency normalization. The objective is `(0.75 × posterior_quality + 0.15 × economy + 0.10 × speed) × reliability`. Ties prefer lower configured cost, lower estimated latency, then lexical model IDs. Completed plans preserve all scores and selected model snapshots.

## Inspecting measured usage

```sh
loom metrics --profile default
loom metrics --profile default --run RUN_ID
```

Only integer, nonnegative `usage.prompt_tokens` and `usage.completion_tokens` within a bounded range are retained from chat responses. Other provider usage fields are discarded. Missing or invalid usage does not invent zero consumption and does not by itself invalidate a successful creative artifact. When both rates are configured, cost is calculated from the frozen card, not whichever configuration exists when the report is opened.

`priced_steps` and `unpriced_steps` report token-estimate coverage. The subtotal is **not total spending**: images, speech and local tools have no token estimate here, and unknown remote effects may have been billed. Measured usage does not currently replace the planner's per-call cost estimate.

`forget PROFILE` removes preferences, feedback and measurement rows used by future decisions. Frozen run artifacts, embedded measurements, practice, evaluations and audit events remain. This is a local decision reset, not a full data-erasure API.

Music planning uses `song:lyrics` and `song:direction` task scopes. These score text planning outputs, not the quality of music generated outside the application. A bound reference audio asset is provenance for the operator; it is not passed as multimodal input to the current text adapters.

`research:synthesis` is a text decision task for evidence synthesis, separate from creative-quality feedback. The synthesis plan suppresses active editorial guidance to avoid recursively biasing evidence interpretation. A task-scoped method records the effective inherited/editorial method on each creative step; the active method root alone does not imply that every task uses the newest instruction.
