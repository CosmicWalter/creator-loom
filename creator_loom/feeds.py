"""Bounded public feed ingestion. Returned material is untrusted evidence."""

from __future__ import annotations

import ipaddress
import subprocess
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from . import __version__

HOSTS = {"github.com", "huggingface.co", "arxiv.org", "export.arxiv.org"}
LIMIT = 2 * 1024 * 1024


class FeedError(ValueError):
    pass


def source_url(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("Evidence URL must be a bounded HTTPS URL without whitespace")
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment
                or u.port not in {None, 443}):
            raise ValueError("Invalid evidence URL")
        host = u.hostname.lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
            raise ValueError("Evidence URL must identify a public source")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Evidence URL must identify a public source")
        if any(k.lower() in {"token", "key", "api_key", "access_token", "password", "auth", "signature"}
               for k, _ in parse_qsl(u.query)):
            raise ValueError("Evidence URL must not contain credential parameters")
    except (ValueError, TypeError):
        raise ValueError("Evidence requires a public HTTPS URL without credentials, fragments or nonstandard ports") from None
    return url


def feed_url(url):
    source_url(url)
    u = urlsplit(url)
    if u.hostname not in HOSTS:
        raise ValueError("Feed hosts must be GitHub, Hugging Face or arXiv")
    query = parse_qsl(u.query, keep_blank_values=True)
    allowed = {"search_query", "start", "max_results", "sortBy", "sortOrder"} if u.hostname.endswith("arxiv.org") else set()
    if any(k not in allowed for k, _ in query):
        raise ValueError("Feed URL contains unsupported query parameters; do not put credentials in URLs")
    return url


def canonical_link(link, base):
    u = urlsplit(urljoin(base, link))
    scheme = "https" if u.scheme == "http" and u.hostname in HOSTS else u.scheme
    clean = urlunsplit((scheme, u.netloc, u.path or "/", u.query, ""))
    source_url(clean)
    u = urlsplit(clean)
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    host = u.hostname.lower()
    netloc = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", netloc, u.path or "/", urlencode(sorted(query)), ""))


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        tag = tag.rsplit(":", 1)[-1]
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"p", "br", "div", "li"} and not self.skip:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        tag = tag.rsplit(":", 1)[-1]
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip-1)
        elif tag in {"p", "div", "li"} and not self.skip:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value, limit):
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())[:limit]


def parse_feed(raw, url):
    if len(raw) > LIMIT:
        raise FeedError("Feed exceeded the two-megabyte limit")
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        elif raw.startswith(b"\x00<\x00?"):
            text = raw.decode("utf-16-be")
        elif raw.startswith(b"<\x00?\x00"):
            text = raw.decode("utf-16-le")
        else:
            text = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise FeedError("Feed DTD/entity declarations are not supported")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError):
        raise FeedError("Feed must be valid UTF-8/UTF-16 RSS or Atom XML") from None
    atom = "{http://www.w3.org/2005/Atom}"
    if root.tag == atom + "feed":
        entries = root.findall(atom + "entry")
    elif root.tag == "rss":
        entries = root.findall("./channel/item")
    else:
        raise FeedError("Response is not an RSS 2.0 or Atom feed")
    results = []
    for entry in entries[:200]:
        def field(*names):
            for name in names:
                value = entry.find(name)
                if value is not None:
                    return (value.text or "") + "".join(ET.tostring(child, encoding="unicode") for child in value)
            return ""
        href = field("link")
        if not href:
            links = entry.findall(atom + "link")
            alternate = next((x for x in links if x.get("rel", "alternate") == "alternate"), None)
            href = alternate.get("href", "") if alternate is not None else ""
        if not href:
            continue
        try:
            link = canonical_link(href.strip(), url)
        except ValueError:
            continue
        title = plain(field("title", atom + "title"), 500)
        if not title:
            continue
        results.append({"title": title, "source": link,
                        "summary": plain(field("description", atom + "summary", atom + "content"), 6000),
                        "published": field("pubDate", atom + "published", atom + "updated")[:100],
                        "state": "discovered", "trusted_for_execution": False})
    return results


class NoFeedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FeedError("Feed redirected; configure its final supported HTTPS URL explicitly")


def curl_feed(url):
    # --disable must be first: never inherit curlrc credentials or insecure flags.
    command = ["curl", "--disable", "--proto", "=https", "--max-redirs", "0", "--fail", "--silent",
               "--connect-timeout", "10", "--max-time", "20", "--user-agent", f"creator-loom/{__version__}",
               "--write-out", "\n%{http_code}", "--url", url]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise FeedError("System curl is unavailable") from None
    try:
        raw = process.stdout.read(LIMIT+5)
        if len(raw) > LIMIT+4:
            raise FeedError("Feed exceeded the two-megabyte limit")
        if process.wait(timeout=25) != 0:
            raise FeedError("System curl feed request failed; TLS verification remains enabled")
        body, separator, status = raw.rpartition(b"\n")
        if not separator or status != b"200":
            raise FeedError("System curl requires HTTP 200; redirects are not followed")
        return body
    except subprocess.TimeoutExpired:
        raise FeedError("System curl feed request timed out") from None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def discover(url, transport="urllib"):
    feed_url(url)
    if transport == "curl":
        return parse_feed(curl_feed(url), url)
    if transport != "urllib":
        raise ValueError("Feed transport must be urllib or curl")
    request = urllib.request.Request(url, headers={"User-Agent": f"creator-loom/{__version__}"})
    try:
        with urllib.request.build_opener(NoFeedRedirect).open(request, timeout=20) as response:
            if response.status != 200:
                raise FeedError("Feed requires HTTP 200")
            raw = response.read(LIMIT+1)
    except (OSError, urllib.error.URLError):
        # Do not echo transport errors: they may contain URLs, proxy details or credentials.
        raise FeedError("Feed request failed; check network and trusted CA configuration") from None
    return parse_feed(raw, url)
