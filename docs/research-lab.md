# Evidence-bound research lab

This flow takes explicitly selected public feed metadata through model synthesis, human review, a preassigned held-out comparison and reversible task-scoped activation. It is not autonomous code updating, full-paper research, license verification, semantic retrieval, model training or proof of creative improvement. It uses the same configured text adapters and model constraints as creation.

## Select and synthesize

In the local workbench, open **学习雷达**, choose **模型辅助整理** on a collected item, select 1–4 evidence items and the creative task to improve, and enter a goal and synthesis budget. The application freezes exact item revisions, metadata hashes and snapshots. It reserves a normal run; inspect its frozen plan before explicitly executing it. No implicit inference runs on feed refresh.

CLI equivalent:

```sh
loom --config config.local.json lab-new clarity-study --spec lab.local.json --key clarity-study
loom lab-inspect clarity-study
loom inspect SYNTHESIS_RUN
loom execute SYNTHESIS_RUN
loom lab-draft clarity-study
loom approve SYNTHESIS_RUN
```

Spec:

```json
{
  "task": "novel:chapter",
  "sources": [{"item": "COLLECTED_ITEM_ID", "revision": 1}],
  "goal": "Investigate one bounded editorial method for chapter clarity, retaining evidence limits.",
  "profile": "default",
  "language": "zh",
  "budget": 1,
  "local_only": true,
  "max_latency": 300
}
```

`research:synthesis` is a separate internal text recipe. It receives selected title/summary/date/link snapshots as untrusted data. It does not fetch linked full text or import code/assets. Active editorial guidance is suppressed during synthesis. Profile preferences and the research goal still enter the normal frozen prompt: inspect them before choosing a remote model. Prompt instructions are not a security boundary against malicious model text; there is no executable tool channel here.

The output must be a strict JSON proposal containing an explicit target task, hypothesis, bounded guidance, exact citations, license cautions, editorial compatibility, limitations and 6–12 distinct original test topics. Quotations must match 20–500 characters of an actually selected title/summary revision. This catches fabricated quotations, not unsupported interpretation, misleading context or scientific validity. A complete `insufficient` result with task/reason is valid and cannot create a technique. Malformed output remains an artifact; it is not silently repaired or retried.

## Review before accepting

Approval of the actual synthesis file is followed by separate source/inference, license and compatibility reviews and explicit authorization for the proposed original/licensed test cases. No checkbox proves legal rights or source validity. Do not approve a method that requires undocumented tools, installation or permissions: this feature is bounded editorial guidance only.

```sh
loom lab-accept clarity-study clearer-scenes --review review.local.json
```

Review fields are `note`, `license_review`, `compatibility_review` (each 10–2000 characters) and `cases_authorized: true`. They are local evidence, not public artifacts. At acceptance, selected evidence must still be current and not dismissed, and the active baseline must match the one reserved at synthesis. Changed evidence/baseline requires another synthesis. Acceptance freezes the method, quotations, source snapshots and review, and creates a **proposed**, inactive technique scoped to one task.

Existing manual research proposals remain available. They are a separate workflow and do not acquire model-grounding or holdout guarantees retroactively.

## Preassign a comparison

```sh
loom --config config.local.json lab-experiment clarity-study --settings experiment.local.json
```

Settings example: `{"total_budget": 1, "local_only": true, "max_latency": 300}`. This is the total conservative configured cost estimate across all paired plans, not a runtime spending cap or provider invoice. It is divided across both arms of every case; execution latency limits remain per run. The candidate uses exactly the paired baseline models. Plans stop at the selected target, and upstream creative artifacts are verified/copied from the baseline rather than regenerated.

The original accepted test topics, plans, model/settings snapshots, random development/holdout assignment and A/B order persist before generation. Topics differing in text do not prove independence. Configuration changes cannot retune the frozen experiment. If existing model settings cannot satisfy its constraints, planning fails without inference. Another experimental design needs another retained study.

Use the workbench or `benchmark-inspect EXPERIMENT_ID`, `benchmark-generate`, `benchmark-packet`, `benchmark-review` and `benchmark-seal` from [model benchmarks](benchmarks.md). Generate the control arm before candidate so shared upstream inputs exist. Async targets retain the original waiting/reconciliation rules and run IDs. Unknown effects are never replayed automatically.

Review both actual outputs with a consistent 0–1 rubric and a meaningful rationale. Scores cannot be overwritten. The ZIP includes only A/B target creative files, direct shared inputs and minimal brief/review information. Content can reveal identity; local owners can inspect mappings. This is presentation blinding, not secure or independent reviewer isolation.

Complete and seal development scores before holdout generation/review opens. Approve the actual holdout outputs before evaluation. The workbench can approve both inspected outputs of a case. Development observations remain exploratory and do not enter the activation threshold or model feedback.

## Evaluate, activate, recover

```sh
loom lab-evaluate clarity-study
loom lab-promote clarity-study
loom lab-rollback clarity-study
```

Evaluation uses exactly the stored holdout pairs, ratings and rationale; the generic technique evaluator cannot replace them with new scores or development cases. The current workflow gate is mean delta ≥0.05 and worst delta ≥−0.1, reusing the existing editorial gate. This is a small human-scored workflow threshold, not statistical superiority. Reports retain separate development/holdout outcomes and a descriptive one-sided sign test through `benchmark-report`; do not combine them into an independent creative-quality claim. Technique trials cannot calibrate model feedback.

Activation is explicit and rechecks approved synthesis/output hashes, evidence provenance, held-out ratings and the active baseline. An accepted historical snapshot remains historical evidence if a feed later changes; new feed content does not silently rewrite earlier plans or retire methods. The UI flags stale selected evidence, while ongoing experiments keep their reviewed frozen sources.

The method applies only to its selected task. Other tasks keep the frozen effective inherited instruction, recorded per step. New baseline snapshots use hash references and flattened inherited method maps rather than recursively embedding all prior studies. Older inline baselines remain readable. Mutation/loss of required baseline records blocks adoption; do not edit the state database as an update mechanism.

Rollback restores the prior active method root and remains available even if an experiment/source artifact was lost. It does not erase runs, reviews or provenance. `forget PROFILE` is personalization reset, not erasure of research studies.

## What verification proves

Synthetic tests cover frozen evidence, literal quote matching, refusal/invalid schemas, license/case gates, changed evidence/baseline rejection, task-scoped inheritance, forty bounded updates, shared-prefix trials, immutable development/holdout scoring, model-feedback isolation, activation tamper checks and recovery rollback. Real authenticated HTTP tests exercise the complete workbench API chain with simulated inference and fixture ratings. JavaScript syntax and packaged assets are checked separately.

These are protocol and HTTP results. Real model synthesis quality, valid source interpretation, genuinely independent review, general creative gains and browser/mobile usability have not been established. No provider model was available for a live generation in this update.
