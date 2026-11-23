# Model-assisted continuity proposals

A model can suggest character facts from an accepted episode, but those suggestions must not silently become story truth. This flow freezes an accepted text artifact and current reviewed character memory, reserves one normal model run, validates its structured candidate output, and applies only explicitly selected human-reviewed changes as another memory version.

It does not autonomously execute inference on chapter acceptance, resolve semantic contradictions, read unaccepted drafts as continuity, rewrite a complete memory or guarantee narrative consistency.

## Reserve a plan

After explicitly accepting at least one episode, choose **模型辅助连续性建议** on the series in the workbench book shelf. Set the configured cost estimate/local-model preference and save a plan. The normal run detail shows the frozen model, input and constraints. Execute it explicitly; refreshing does not submit another inference.

CLI:

```sh
loom --config config.local.json continuity-new after-first-chapter SERIES_ID \
  --settings continuity.local.json --key after-first-chapter
loom continuity-inspect after-first-chapter
loom inspect PROPOSAL_RUN_ID
loom execute PROPOSAL_RUN_ID
loom continuity-draft after-first-chapter
```

Settings: `{"budget":1,"local_only":true,"max_latency":300}`. These remain planning estimates, not measured invoices or runtime guarantees. The internal `continuity:facts` text recipe is reserved through this flow, not as an ordinary creation recipe without evidence.

The selected evidence is the latest **accepted** episode of this same series and its last text step (e.g. chapter, spoken script or article draft). The complete approved run and selected artifact are verified. The current memory and series versions are frozen; a pending episode prevents reserving another continuity plan.

Only accepted creative text and the names/fact handles needed to preserve identity enter the analysis prompt. Series/run identifiers, artifact paths, citations' operation handles and private review notes are not included. Profile preferences remain part of the normal plan, so inspect them and the local/remote setting before execution. Active creative editorial guidance is suppressed for the analysis. The selected model must fit the entire input; the application does not silently trim away evidence to fit an undersized model.

## Validate candidate output

The model must return a complete JSON object with `status: "suggestions"`, summary, at most twelve changes and at most twelve uncertainty warnings. Each change includes:

- Existing `character` ID and exact display `name`, or null ID for a proposed new character.
- Existing `fact` ID for an explicit replacement, or null for an addition.
- Supported fact category, bounded proposed text and a 5–400 character exact quote from the accepted episode.
- A reason explaining support, ambiguity, temporal scope and any apparent conflict.

Unknown IDs, silent renames, duplicate edits/replacements, fabricated quotes and extra executable-schema fields are rejected. Plain text, fenced JSON or malformed output is not automatically repaired or rerun. A valid empty changes list means there is no supported update; it cannot create an empty automatic memory revision.

Literal matching only proves that the quoted characters occurred in the accepted output. It does not prove entailment, correct pronouns, identity disambiguation, persistent state, original-source faithfulness or legal rights. The model's warning/reason is a suggestion, not a verified contradiction detector. In particular, an event such as opening a shutter may be transient rather than a lasting character fact.

## Review and accept only selected changes

First inspect and approve the actual model-output artifact. Then review each change in the workbench; proposed replacements show the old fact. Do not select a change you cannot support. The explicit human review must assess character identity, quote interpretation, conflicts, timeline scope and the replacement decision.

```sh
loom approve PROPOSAL_RUN_ID
# Candidate indexes are zero-based; repeat --selected for more than one.
loom continuity-accept after-first-chapter --selected 0 \
  --reviewed --note 'Checked the quoted action, character identity and temporal scope; retained other facts.'
```

Only selected additions/replacements are materialized. Existing unselected characters/facts remain unchanged; new character/fact IDs are created locally. Existing IDs are retained for replacements. The normal character/fact/count/serialized-size limits still apply. Adding an exact duplicate of an existing fact or making no change is rejected.

The memory revision and proposal acceptance commit atomically. A failure between writes rolls back both. Review decisions, selected indexes and resulting memory version are retained. Repeating the same acceptance returns that record; a different selection/note cannot overwrite it. Old memory versions and old chapter plans remain intact.

If another memory revision, series acceptance/rejection or pending chapter intervenes, the proposal is stale and cannot be applied. Retain it for historical inspection and explicitly plan another suggestion against the current state. A historical output still binds the frozen evidence, not whatever content is latest today. Changed/deleted accepted evidence or model-output artifacts block parsing/application instead of rebinding old text to new content.

This flow does not change free-form continuity notes, advance a source cursor or publish anything. These remain their existing explicit actions. Personalization reset does not erase suggestion/review/provenance history.

## Validation and remaining evidence

Original fictional sources, simulated model JSON and actual authenticated HTTP tests cover frozen accepted inputs, no implicit inference, stable reservation keys, exact quotes/IDs, invalid outputs, empty results, explicit artifact and change approval, selected additions/replacements, historical memory, stale rejection, tamper blocking and atomic rollback after a synthetic persistence failure.

These validate protocol behavior, not real model fact extraction accuracy or improved long-form quality. Live model consistency comparisons, semantic contradiction evaluation, temporal fact lifetimes, cast retrieval and browser/mobile interaction acceptance remain pending.
