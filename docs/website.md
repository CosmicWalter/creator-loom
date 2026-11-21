# Public project website

Live: **https://cosmicwalter.github.io/creator-loom/**

The buildless project website lives in `website/`. It introduces actual capabilities, offers four clearly labeled workflow demonstrations, links directly to usage documentation, and copies installation commands on request. It does not run models, connect to the local workbench, collect briefs, load remote scripts/fonts, or send analytics. GitHub Pages serves it as a public static website; hosting-level request handling remains GitHub's responsibility.

The public website is separate from the authenticated loopback creation workbench. Do not put model credentials, access codes, private configuration, user artifacts, screenshots containing identifying information or operational data in its source.

## Checks and publication

```sh
python3 scripts/check_website.py
node --check website/app.js
python3 scripts/check_publication.py
python3 scripts/publish_pages.py
# After reviewing the source and checks:
python3 scripts/publish_pages.py --publish
```

The default publication command only checks readiness. With `--publish`, it verifies the actual `gh` session is `CosmicWalter`, checks the HTTPS repository destination and rejects transport overrides. It builds a separate Git tree containing exactly the five allowlisted website files and appends a pseudonymous, unsigned UTC-dated commit to `gh-pages`. It uses the verified `gh` credential helper for the push, never force-pushes, and does not include the application source, working-tree history or private data in the deployed tree. Existing website history must also use the authorized identity. Concurrent branch updates cause a normal push failure rather than overwriting another change.

Repository Pages settings should serve the root of `gh-pages` using branch-based builds. Publication is an explicit developer action, not a timed automation or a workflow that pushes with a bot identity. Future website changes need another reviewed publication. The release label is checked against the package version, so a version bump requires updating the public status as well.

Structural checks cover expected files, IDs, local assets, documentation targets, the initial tab state and the release label. They do not prove responsive rendering, keyboard interaction, clipboard behavior or visual quality. Browser acceptance remains pending when supported browser access is unavailable. Public HTTP checks verify deployment availability and content only.

The initial deployment was confirmed by the successful GitHub Pages build/deploy run and `built` Pages state. Public HTTPS responses for HTML, CSS, JavaScript and SVG matched the reviewed source bytes. These checks verify availability and content integrity, not browser interaction or visual acceptance.
