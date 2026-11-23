# Reviewed character memory

Sequential book adaptation needs stable story facts, not just another unconstrained summary. Series now support bounded character records with exact source citations and explicit human review. The feature preserves reviewed memory versions in episode plans. It does not adopt facts automatically, validate semantic contradictions, track a complete fictional timeline or guarantee model consistency. The [continuity proposal](continuity.md) flow can ask a configured model to suggest quoted candidate changes, which remain inactive until explicitly selected and reviewed.

## Workbench

In **我的书架**, find a series and select **角色记忆与版本**. Inspect the current or a historical snapshot. When no episode is pending, edit character names and facts, select their evidence, read that source text, copy a literal quotation and write a review note. Confirm that you checked each fact's attribution, temporal scope, character reference and applicability.

Facts are categorized as `identity`, `appearance`, `relationship`, `state` or `constraint`. These labels aid inspection; they are not a knowledge-graph reasoning engine. A human may conclude that a sentence supports a fact, but the application only proves literal quotation presence and hash/provenance integrity. The text can be ambiguous, fictional, misleading or in conflict with other facts. Review these issues yourself.

Saving creates another immutable memory version and increments the series optimistic version without advancing the source-unit cursor. Existing episode plans do not change. Restoration from history copies that snapshot into a new reviewed revision; it does not overwrite history. Removing a character/fact is permitted in a newly reviewed snapshot and preserves earlier versions. An unchanged snapshot is rejected rather than duplicated.

The editor does not persist unsaved form drafts across closing/reloading; save or retain your work before leaving. Browser interaction/visual acceptance remains pending.

## Citation boundaries

A source citation identifies a unit of this series' imported book. It can use an already visited unit or the current unit awaiting adaptation; it cannot cite a later unvisited unit. The original imported source/unit hashes remain checked. Reading source evidence in the memory editor obeys the same progress boundary.

An episode citation identifies a text step in an **accepted episode of this same series**, whose creative run remains approved and whose cited artifact hash matches. A completed-but-unaccepted or rejected attempt is not accepted story memory. A chapter accepted in another series is not interchangeable even if it uses the same book.

Each quote must be an exact 5–400 character substring. It is stored with the source unit/text output SHA256, not merely a URL or a model assertion. Facts can paraphrase the source only through human judgment; exact quote matching does not establish entailment or truth.

Do not use this as an unreviewed store of personal information. Series and source material remain private local runtime data, but selected creative facts enter configured text/image model prompts. Inspect the plan's actual privacy setting before executing remote models.

## CLI

```sh
loom series-memory SERIES_ID
loom series-memory-update SERIES_ID --spec facts.local.json \
  --base-version SERIES_VERSION --memory-version MEMORY_VERSION \
  --reviewed --note 'Checked each source quote, character reference and temporal scope.'
loom series-memory SERIES_ID --version 1
```

Spec example, for an original fictional book whose current unit actually contains the quoted sentence:

```json
{
  "characters": [{
    "id": "rowan",
    "name": "Rowan",
    "facts": [{
      "id": "role",
      "kind": "identity",
      "text": "Rowan is the lighthouse keeper.",
      "citation": {
        "kind": "source",
        "unit": 0,
        "quote": "Rowan is the keeper of a lighthouse."
      }
    }]
  }]
}
```

An accepted-episode citation instead uses `{"kind":"episode","run":"ACCEPTED_RUN_ID","step":"chapter","quote":"An exact quote from the accepted chapter."}`. The application fills the hash. Normalized payloads retain their hashes and can be edited/reused for the next revision, but updated evidence must be cited rather than retaining a stale checksum.

Limits: at most 30 characters, 1–20 facts per character, 60 facts total and 20000 serialized characters. Names are 1–100 characters; fact text at most 500; review notes 10–2000. IDs are bounded normal project identifiers. An empty character list is a deliberate cleared memory. New/legacy series begin with empty memory version 0, preserving older databases.

## Plan and recovery invariants

`series-next` freezes the current memory alongside source and continuity context. The planner sends only character names and fact categories/text as creative data, not memory database IDs, citations' run handles or private reviewer notes. This extra input is counted in model capacity allocation. It is included only in text/image prompts; speech uses the already generated narration as before.

A pending episode blocks memory changes, so a queued/running/uncertain attempt cannot have its input silently replaced. Finish and accept the actual episode, or use the existing explicit rejection/reconciliation flow. The usual unknown-operation retry rules remain unchanged. Stale series/memory versions are rejected.

Plans, execution, approval and later artifact-bound evaluation validate the frozen memory record and cited evidence. Source/artifact loss or mutation blocks dependent work instead of continuing with unverified facts. A future memory revision does not invalidate an intact earlier memory snapshot. Accepted episode citations validate their actual text file directly rather than recursively revalidating an entire chain of earlier memory contexts.

Comparison packets include the creative character facts needed to judge consistency, while ordinary deliverable bundles still exclude raw plans and private memory history/review notes. Rights, attribution and private-content review still apply to any shared content. Personalization reset does not erase character memory or provenance.

## Evidence and outstanding work

Original fictional text and simulated model outputs exercise source/episode citations, no-future-unit restrictions, cross-series rejection, legacy migration, CLI review, pending locks, version history, frozen prompts and hash-change blocking. Real authenticated HTTP tests cover evidence viewing, review gates, stale updates and chapter acceptance followed by another memory version. They verify the workflow, not actual model faithfulness or narrative quality.

Model-assisted fact proposals are now available through a separate explicit review flow; validated semantic conflict detection, temporal fact lifetimes, retrieval over large casts, real-model continuity comparisons and browser/mobile usability remain separate work.
