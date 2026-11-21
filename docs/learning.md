# Learning contract

Three different learning loops must remain distinguishable:

1. **Personalization**: an explicit profile preference snapshot changes prompts; a reviewed score changes that profile's routing prior for a specific format/stage and model signature. Execution measurements inform conservative latency estimates and smoothed reliability within the same scope. Changing the backend or generation limits isolates its history. No cross-profile or cross-task feedback sharing. These estimates are heuristics, not measured proof of the best creative model.
2. **Technique updates**: subscribed public feed collection → deduplicated, versioned research inbox → human-reviewed evidence and editorial guidance → experimental runs → paired review → activation → possible rollback. Feed revisions do not rewrite a proposed technique's frozen evidence.
3. **Creator development**: `coach` produces medium-specific review questions and a deliberate-revision exercise bound to actual artifacts. `practice` retains a changed revision, original hash, rubric dimension, before/after scores and a rationale. `progress` aggregates self-reported revision deltas per profile. These records support reflection, but do not prove that users become more skilled.

## Paired review file

Create baseline and experimental runs for at least three distinct topics. The briefs must match exactly, including profile, language, format, budget, privacy and latency target. Use `--technique ID` only for experimental runs. Execute each, inspect actual artifacts and explicitly approve. Then prepare a local JSON array (not committed with private run IDs):

```json
[
  {
    "baseline": "BASELINE_RUN_ID_1",
    "candidate": "CANDIDATE_RUN_ID_1",
    "baseline_score": 0.6,
    "candidate_score": 0.7,
    "rationale": "Describe the actual editorial difference and the rubric used."
  },
  {
    "baseline": "BASELINE_RUN_ID_2",
    "candidate": "CANDIDATE_RUN_ID_2",
    "baseline_score": 0.7,
    "candidate_score": 0.8,
    "rationale": "Describe the actual editorial difference and the rubric used."
  },
  {
    "baseline": "BASELINE_RUN_ID_3",
    "candidate": "CANDIDATE_RUN_ID_3",
    "baseline_score": 0.5,
    "candidate_score": 0.6,
    "rationale": "Describe the actual editorial difference and the rubric used."
  }
]
```

Numbers above illustrate the file format; they are not measured results. Scores are normalized 0–1. Current gate: average improvement at least 0.05, no individual regression greater than 0.1. Artifacts are rehashed at evaluation and promotion. Reused topics or run IDs, missing review, wrong technique provenance and different briefs are rejected.

Models, model parameters represented in their cards, profile preferences, workflow steps and the baseline technique are now frozen and checked between pairs. A proposal records the active technique at proposal time; promotion is rejected if that active baseline has since changed. This controls some confounds, but not stochastic generation, reviewer expectations, provider-side version changes or all other factors.

These are small human-scored experiments. They can be biased or noisy; passing is permission for a reversible local trial, not proof of universal improvement. Blind scoring, holdout samples, richer generation parameters and confidence intervals remain future work.

## Threat boundaries

Feed ingestion runs manually or in an explicitly started foreground `research-worker --watch`. Per-source due times and short leases survive restarts. Only supported public HTTPS feed hosts are fetched, redirects are rejected, document types are rejected and response size is limited. Python TLS is the default; an explicit system curl transport retains certificate validation and disables personal curl configuration. Fetched content is never executed or automatically promoted. Discovery does not verify scientific claims, license rights or runtime compatibility. See [research inbox](research-inbox.md) for the version/review contract.

Techniques contain short editorial instructions and source links, not executable plugins. A source link is evidence to inspect, not a verified endorsement. This version does not install dependencies, download weights, rewrite source code, change production services, or publish content automatically. Such future capabilities need sandboxed proposals, reproducible evaluation and explicit deployment records.

Rollback changes future plans. Existing runs keep their frozen technique and prompts for reproducibility.

## Task-scoped synthesis experiments

Model-assisted proposals use the [research lab](research-lab.md), which binds selected evidence and the synthesis artifact, requires manual source/license/compatibility review, and permits only the stored held-out scores in evaluation. These proposals cannot bypass the reserved experiment through generic evaluate. Effective editorial methods are saved per step; a scoped activation preserves the frozen inherited method on other tasks. New baseline snapshots are hash references rather than recursively copied payloads; legacy inline snapshots remain readable. Missing/changed referenced baseline records block evaluation/promotion, while rollback remains available for recovery.
