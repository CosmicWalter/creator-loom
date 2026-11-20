# Learning contract

Three different learning loops must remain distinguishable:

1. **Personalization**: an explicit profile preference snapshot changes prompts; a reviewed score changes that profile's routing prior for one modality. No cross-profile feedback sharing.
2. **Technique updates**: public feed discovery → human-authored, sourced editorial guidance → experimental runs → paired review → activation → possible rollback.
3. **Creator development**: future editorial exercises, self-assessment and progress evidence. This is not yet implemented; preference storage alone does not prove that users become more skilled.

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

These are small human-scored experiments. They can be biased, insufficiently controlled or noisy; passing is permission for a reversible local trial, not proof of universal improvement. Future work should freeze model snapshots and all non-technique factors, support blind scoring, holdout samples and confidence intervals.

## Threat boundaries

Feed ingestion is an explicit command, not a background scheduler. Only supported public HTTPS feed hosts are fetched, redirects are rejected, document types are rejected and response size is limited. Fetched content is never executed or automatically promoted. Discovery does not verify scientific claims, license rights or runtime compatibility.

Techniques contain short editorial instructions and source links, not executable plugins. A source link is evidence to inspect, not a verified endorsement. This version does not install dependencies, download weights, rewrite source code, change production services, or publish content automatically. Such future capabilities need sandboxed proposals, reproducible evaluation and explicit deployment records.

Rollback changes future plans. Existing runs keep their frozen technique and prompts for reproducibility.
