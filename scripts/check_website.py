"""Buildless website structure/link checks; not browser or visual acceptance."""

from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = {"index.html", "style.css", "app.js", "mark.svg", ".nojekyll"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.tabs, self.panels, self.scripts = [], [], [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        for key in ["src", "href"]:
            if attrs.get(key):
                self.links.append(attrs[key])
        if attrs.get("role") == "tab":
            self.tabs.append(attrs)
        if attrs.get("role") == "tabpanel":
            self.panels.append(attrs)
        if tag == "script":
            self.scripts.append(attrs.get("src"))
        if tag in {"form", "iframe"}:
            raise ValueError("Public site must not collect data or embed third-party pages")
        if any(key.startswith("on") for key in attrs):
            raise ValueError("Inline script handlers are not allowed")


def check(root=ROOT):
    site = root/"website"
    names = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    if names != FILES or any(p.is_symlink() for p in site.rglob("*")):
        raise ValueError("Website file allowlist changed; inspect publication contents")
    page = Page()
    html = (site/"index.html").read_text()
    page.feed(html)
    if len(page.ids) != len(set(page.ids)):
        raise ValueError("Duplicate HTML IDs")
    for link in page.links:
        url = urlsplit(link)
        if url.scheme:
            if not link.startswith("https://github.com/CosmicWalter/creator-loom"):
                raise ValueError("Unexpected external link or dependency")
            prefix = "/CosmicWalter/creator-loom/blob/main/"
            if url.path.startswith(prefix) and not (root/unquote(url.path[len(prefix):])).is_file():
                raise ValueError("Repository documentation link is missing")
            continue
        if url.netloc or url.path.startswith("/"):
            raise ValueError("Use project-relative website assets")
        if url.path and not (site/unquote(url.path)).is_file():
            raise ValueError("Website asset link is missing")
        if url.fragment and not url.path and url.fragment not in page.ids:
            raise ValueError("Website anchor is missing")
    if page.scripts != ["app.js"]:
        raise ValueError("Unexpected website scripts")
    for tab in page.tabs:
        if tab.get("aria-controls") not in page.ids:
            raise ValueError("Tab panel is missing")
    if len(page.tabs) != 4 or sum(t.get("aria-selected") == "true" for t in page.tabs) != 1:
        raise ValueError("Invalid initial tab state")
    version = tomllib.loads((root/"pyproject.toml").read_text())["project"]["version"]
    if f">v{version}<" not in html:
        raise ValueError("Website release label is stale")
    js = (site/"app.js").read_text()
    for target in re.findall(r'querySelector\("#([a-zA-Z0-9_-]+)"\)', js):
        if target not in page.ids:
            raise ValueError("Website script target is missing")
    for relative in re.findall(r'link: "([^"#]+)(?:#[^"]*)?"', js):
        if not (root/relative).is_file():
            raise ValueError("Demo documentation link is missing")
    print("Website structure, release label, local assets and documentation links passed; browser acceptance pending.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(check())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
