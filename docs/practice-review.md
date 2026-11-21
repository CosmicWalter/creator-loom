# Blind revision comparisons

A changed artifact and an optimistic self-score do not establish that a creator became more skilled. This workflow adds a separate comparison record for actual original/revised text with hidden version labels. It is evidence about the scored revision, not durable learning, causal benefit, transfer performance or verified reviewer independence.

## Save a real revision

Use **创作复盘与练习** on a finished work, or the existing CLI:

```sh
loom practice RUN_ID chapter --revision revision.txt --dimension clarity \
  --before 0.4 --after 0.7 --rationale 'Explain a concrete edit and the original self-assessment.'
```

The original self-ratings remain self-report data. The revision must differ from the original and is saved under a generic local filename with its original hash. This feature currently supports only finished text stages, UTF-8 plain text without NUL bytes, at most 1 MB per version. Other media retain normal coaching and feedback; they do not receive an unvalidated blind reviewer interface.

## Prepare the comparison

Open **成长记录** and choose **准备 A/B 评审** for a saved practice. The CLI equivalent is:

```sh
loom practice-blind PRACTICE_ID
loom practice-review-inspect REVIEW_ID
loom practice-review-packet REVIEW_ID
```

Creating the same practice comparison twice returns the same stored review and A/B order. It never reruns model inference. The comparison freezes the original and revision hashes, creative brief, rubric dimension and available direct shared text dependencies. Book-based work also carries the authorized source text and accepted continuity. It validates all original run artifacts, not just the displayed target, and preserves required public credits.

The local ZIP contains `A.txt`, `B.txt`, `review.json` and shared text files when applicable. It excludes original self-ratings, original editing rationale, model/run/profile identity, endpoints, operational metadata, local filenames/paths and the original/revised mapping. The archive uses neutral timestamps. The creative content and public credits still require privacy/rights review before sharing; it does not automatically redact information inside a work. Source excerpts may require permission to share. Download only prepares a local artifact and does not send it to another person.

Blinding is presentation-level only. A local owner can read stored mappings or remember a draft, and content can reveal which version was revised. Sending a package to another reviewer is a separate user action. The application does not authenticate reviewers, assign them independently or establish that they avoided prior scores and editing notes.

## Score, then reveal

Use the same rubric to score both presented versions on 0–1, with a 10–4000 character rationale. Declare `self` for the creator's own comparison or `external-declared` when another reviewer supplied the scores. Do not enter a real name or personal contact information: this records a reviewer role, not identity verification.

```sh
loom practice-review-score REVIEW_ID --a 0.5 --b 0.6 \
  --reviewer-kind external-declared \
  --rationale 'Describe the actual differences using the same rubric for both outputs.'
loom practice-review-report REVIEW_ID
```

The review and declaration are immutable once saved. Score submission reveals the original/revised scores and revision delta; the report endpoint refuses to reveal the mapping before scores exist. The workbench also previews A/B content and provides the same neutral review packet. A source or revision change blocks preview/export/scoring/report rather than applying old scores to a new work.

## Interpret the growth view

`loom progress PROFILE` and the workbench show the existing self-reported revision history separately from `blind_revision_reviews`. Blind summaries are grouped by dimension and `self` / `external-declared`. They use valid bound comparisons only. Missing/changed artifacts are counted in `invalidated_comparisons`, preserving visibility that a comparison was excluded. Scores may disagree with the original self-assessment; they do not overwrite it.

These are selected revision pairs with a declared review role. Sample selection, correlated tasks, remembered drafts, scorer bias and small samples limit inference. An improved revision does not establish that the creator will perform better unaided on a new task or retain the skill over time. There is no control group, preassigned reviewer identity, transfer-task protocol or causal estimate here. Practice review scores never calibrate model routing or activate editorial techniques.

`forget PROFILE` resets personalization, not saved practice, comparisons or audit history. Retained artifacts are local runtime data and excluded from source publication.

## Verification

Tests use original synthetic text, simulated model outputs and fixture ratings. They cover stable randomized packets, same shared inputs, hidden original self-scores, public credits, invalid text/scores, immutable reviewer declarations, contradictory self/external scores, source/revision tampering, profile separation and routing-feedback isolation. Real authenticated HTTP tests cover preview, ZIP, scoring, report, access boundaries and invalidated summaries. Syntax and wheel assets are checked separately. Browser interaction/visual acceptance and actual independent creator-skill evidence remain pending.
