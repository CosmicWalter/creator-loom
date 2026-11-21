# Authorized books and reviewed sequential creation

Creator Loom can import bounded long-form sources and adapt them one reviewed unit at a time. The importer and series protocol are functional; generation quality, voice quality and faithful adaptation still depend on the chosen real models and human review.

## Import contract

`book-import FILE --title TITLE --rights owned|licensed|public-domain` requires an explicit rights declaration. Optional `--rights-note` records licensing/provenance context. It does not independently verify rights or download books. The repository's original `examples/lighthouse.txt` is covered by its MIT license and is suitable for a first import test.

Supported inputs:

- TXT: UTF-8 (optional BOM), UTF-16 with BOM, or strict GB18030 fallback. Chinese chapter headings and English numbered/Roman-numeral chapter headings are detected heuristically. Nonempty introductory text becomes its own opening section.
- EPUB: unencrypted archive, container/package XML and HTML chapters in spine order. No archive extraction, script execution, stylesheet processing, remote resource fetching or OCR. Visible body/license text is retained. Encryption manifests, repeated spine IDs, external/traversing content references and package XML DTD/entity declarations are rejected. Packages using font obfuscation manifests are currently rejected too.

Limits: 8 MB source file, 32 MB declared archive expansion, 2048 archive/spine entries, 8 MB per unpacked entry, two million imported text characters and 10000 units. Units default to at most 4000 characters; `--unit-chars` accepts 200–20000. Long chapters split at a nearby paragraph/sentence boundary or a hard character boundary. Whitespace normalization is not typography-preserving, and this is not a fixed-layout EPUB renderer. PDF/MOBI/DRM are not supported.

The raw source is retained as `library/BOOK_ID/source.bin` under the chosen data directory, alongside the database's normalized units and SHA256 digests. Original filenames, local source paths and EPUB head metadata are not copied into records. These exclusions do not remove visible third-party attribution or licenses from the imported text. The library is private runtime data and is ignored by Git.

`book-inspect BOOK_ID` lists unit metadata; `--unit N` explicitly prints one source excerpt and its provenance. Unit indexes start at zero. Check these units before generating, particularly inferred chapter boundaries and introductory/license material.

## One-off adaptations

Use `plan` or `create` with `--book BOOK_ID --unit N` and optionally `--continuity TEXT`. The source excerpt, rights note and continuity are frozen in the run. They are included as data in text/image prompts and counted against model input limits. Speech receives the generated narration, not the editor's instructions or raw rights metadata. A novel run adapts the selected unit using its outline rather than repeatedly asking for an opening chapter.

```sh
loom --config config.local.json plan '改编为简洁中文叙事' --format novel --book BOOK_ID --unit 1
loom --config config.local.json create '改编为简洁中文叙事' --format novel --book BOOK_ID --unit 1
```

Imported raw/unit hashes are checked before planning, execution and approval. Tampering or deleting the source blocks progress. Frozen source context is also part of paired technique evaluation: changing chapters or continuity cannot masquerade as a controlled technique improvement.

## Series protocol

`series-new` stores a fixed brief and source book, an optional start unit, and up to 4000 characters of initial continuity notes. Supported formats are article, novel, podcast, bookcast and talkshow. Model configuration is supplied when planning each episode; already planned runs retain their model snapshots.

1. `series-next SERIES_ID` atomically reserves a run for the current source unit. Repeated/concurrent calls return that run instead of creating more inference tasks. It does not call models by itself.
2. Inspect the run, execute it, and review the actual deliverables. `approve RUN_ID` binds all artifacts to hashes.
3. `series-accept SERIES_ID RUN_ID --base-version VERSION --continuity TEXT` rechecks source/artifact integrity and advances exactly one unit. It stores the reviewed continuity for subsequent episodes. A stale version, wrong pending run or incomplete/unapproved output is rejected.
4. Inspect the updated series version, then explicitly call `series-next` again. The final accepted unit marks the series consumed; further next calls cannot create extra episodes.

Continuity is a human-curated summary, not autonomous character extraction or a guarantee against hallucinated plot details. Keep character identities, established facts, timeline and unresolved questions explicit. Empty notes are permitted as an intentional reset. Longer character databases, automatic memory proposals, subtitle/scene timelines and shot-level reviews remain future work.

Database transactions reserve episodes and update version/cursor state atomically. Raw files and database state are not a distributed transaction, and local filesystem mutation during a check remains outside an adversarial security boundary. This is a single-user tool, not a tenant-isolated service.

## Rejection and uncertainty

```sh
loom series-reject SERIES_ID RUN_ID --base-version VERSION \
  --reason '文稿需要重新制作，保留本次产物作为审阅记录。'
```

Rejection retains the same source unit and continuity, clears the pending reservation and increments the version. An unexecuted plan is cancelled so it cannot later be executed accidentally. Completed evidence is retained with the rejection reason. A subsequent explicit `series-next` creates a new attempt, which may incur new costs; there is no automatic retry.

An uncertain or externally waiting operation requires `--provider-checked` in addition to a reason. Use this only after reconciling the provider-side outcome and deciding that another attempt is appropriate. The declaration is an operator assertion, not automated reconciliation. The old run and remote receipts remain in history. An executing run cannot be detached, even with this flag. MediaFlow checkpoints can be resumed after obtaining the process-lifetime execution lock; unknown synchronous operations still require manual handling.

`series-inspect` shows cursor, version, pending run and accepted/rejected attempts. Source books and series notes are retained by `forget`; it only resets personalization/decision inputs. Back up the database, `library/` and `outputs/` together before manual migration or data removal.

## Evidence scope

Tests use original text/EPUB fixtures and simulated model responses. They cover text preservation, spine order, import bounds, provenance, concurrent reservation/acceptance, stale edits, source/artifact tampering and explicit handling of uncertain outcomes. A real HTTP test runs two imported units through narration and actual FFmpeg videos with a simulated inference server. It proves integration and sequential review mechanics, not literary fidelity, human-level narration or customer quality acceptance.

## Reviewed character memory

Series can now retain bounded, categorized character facts with exact original/accepted-episode citations, review notes and immutable history. Future episodes freeze the current memory; editing/restoring memory creates a new revision and increments the series version without advancing the source cursor. Pending episodes lock memory updates. See [character memory](story-memory.md) for workbench, CLI and limits. Plain continuity notes remain separate and are never silently converted into facts.
