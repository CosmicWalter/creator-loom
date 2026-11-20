# Research inbox and continuous collection

Creator Loom can collect configured public feed metadata, preserve evidence history, and turn a reviewed observation into a measurable editorial experiment. Collection is autonomous **within explicitly configured subscriptions** when the foreground worker is running. Technique interpretation, evaluation scoring and activation remain reviewed operations. This does not install models, train weights, run downloaded code or modify the agent's source.

## Configure a source

```sh
loom source-add comfyui https://github.com/Comfy-Org/ComfyUI/releases.atom \
  --keyword image --keyword video --keyword audio --interval 21600
loom sources
loom research-refresh comfyui
loom research-worker
loom research-worker --watch --poll-seconds 60
```

Intervals are per-source, 300–604800 seconds. `research-refresh SOURCE` explicitly refreshes an enabled source now; without a source it checks only due subscriptions. `research-worker` defaults to one pass and exits. `--watch` repeats due checks in the foreground; stopping it stops collection. It does not install a daemon or a Codex development automation. Due times and source state are retained in the local database.

To pause or change a subscription, use its displayed version:

```sh
loom source-set comfyui --base-version 1 --disabled
loom source-set comfyui --base-version 2 --enabled --keyword workflow --interval 43200
# --clear-keywords removes keyword filters; it does not delete evidence.
```

Disabling a source stops future fetches, not retention of earlier observations. Concurrent refreshes use a 120-second lease. A configuration change or replacement lease invalidates an old in-flight observation. A crashed collector's lease expires; public GET requests may then be retried. This mechanism applies to non-generative evidence fetches, not uncertain paid inference requests.

## Public feed boundary

RSS 2.0 and Atom feeds are supported on GitHub, Hugging Face and arXiv hosts. The collector follows no article links, scripts, images or redirects. It accepts HTTP 200 responses with at most two megabytes, processes at most 200 entries, and rejects XML DTD/entity declarations (including UTF-16 variants). Summaries are flattened to bounded text, with script/style elements excluded. Full articles, model weights, dependencies and scientific verification are outside this collector.

Feed URLs must use HTTPS, no embedded credentials, no nonstandard ports, and supported query parameters only. Common credential parameters and private/local evidence addresses are rejected. Standard tracking parameters and fragments are removed from article identity. Known public arXiv/GitHub/Hugging Face HTTP article links are represented as HTTPS. Article URLs are evidence pointers, not endorsements or fetched/verified content.

The default transport is Python `urllib` with standard TLS trust. If it cannot use a certificate already trusted by the host system, opt in to the system curl transport:

```sh
loom discover https://github.com/Comfy-Org/ComfyUI/releases.atom --transport curl
loom source-set comfyui --base-version 3 --enabled --transport curl
```

Curl must be installed. Its user configuration is disabled; no cookies, auth headers, personal identifiers or browser sessions are loaded by the collector. Proxy/environment and system CA configuration still belong to the operator. Certificate validation remains enabled, redirects are not followed, and output/time are bounded. Transport errors are stored as categories, not raw response bodies or proxy/credential details. A failed source retains its prior observations and is due for retry within at most 900 seconds; other sources continue independently.

## Evidence identity and revisions

Each canonical article URL identifies one item across subscriptions. Distinct normalized title/summary/publication observations get immutable revisions and SHA256 digests. A previously seen snapshot from another feed does not replace a newer observed snapshot or create endless back-and-forth revisions. This history records **observations**, not an independently verified chronology of changes on the article's website.

Items retain sightings from each subscription. Relevance is explained literal title/summary keyword matching, not semantic understanding or a quality/novelty score. Empty keywords retain all observations with score zero. Reconfiguring keywords updates relevance without changing evidence. Disabled subscriptions' historical sightings remain part of the inbox.

```sh
loom research-inbox
loom research-inbox --state changed
loom research-inbox --state all
loom research-show ITEM_ID
loom research-dismiss ITEM_ID --base-revision 1 --note 'This observation is not relevant to the current creative workflow.'
loom research-reopen ITEM_ID --base-revision 2 --note 'The new capability description warrants a fresh review.'
```

An updated observation does not erase dismissal or an existing proposal. `changed` shows items whose current revision differs from the last reviewed revision, including dismissed items. Review requires the displayed revision; stale reviews cannot overwrite newer evidence. Evidence is local runtime data, not a public research dataset by default.

## Propose, evaluate, activate

```sh
loom research-propose ITEM_ID specific-technique --base-revision 2 \
  --note 'Explain what was actually reviewed and why it is applicable.' \
  --guidance 'Write one concrete, testable editorial instruction.'
```

Proposal creation and the item review commit atomically. A dismissed item must first be reopened. Guidance remains bounded editorial text; it is not executable plugin code. The proposal freezes item ID, revision, digest, source/title/summary/date and the review explanation. Later feed edits do not alter it or existing creative plans. There is no automatic activation when new metadata appears, and a changed feed does not automatically retire a previously reviewed method.

Use `create --technique ID` for controlled experimental runs, then the same paired review, `evaluate`, `promote` and `rollback` commands described in [learning](learning.md). A feed-linked proposal cannot bypass those gates. Source evidence still needs human scientific, licensing and compatibility review; manually assigned test scores do not prove creative improvement.

`forget PROFILE` resets personalization only. Research sources, observations, review notes and proposals are retained. This is a single-user local research library, not a private multi-tenant repository or a full erasure API.

## Validation scope

Fixture tests cover RSS/Atom parsing, canonical links, bounded curl behavior, DTD rejection, failed-source isolation, polling leases, expiry/configuration races, persistence, deduplication, stale reviews and atomic evidence-linked proposals through the existing activation gate. A live public ComfyUI release feed was collected with verified TLS using curl and then collected again without duplicate items. That live check validates transport and metadata ingestion, not the scientific or creative value of the release notes.
