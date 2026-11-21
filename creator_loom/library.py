"""Bounded, offline import of explicitly authorized text and EPUB sources."""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .domain import identifier

MAX_FILE = 8 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024
MAX_TEXT = 2000000
HEADINGS = re.compile(
    r"^[ \t]*(?:第[ \t]*[零〇一二三四五六七八九十百千万两\d]+[ \t]*[章节回卷部集]"
    r"|chapter[ \t]+(?:\d+|[ivxlcdm]+)\b|prologue\b|epilogue\b|序章|楔子|尾声|后记)[^\n]{0,100}$",
    re.MULTILINE | re.IGNORECASE,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gb18030")
            except UnicodeDecodeError:
                raise ValueError("Text must be UTF-8, UTF-16 with BOM, or GB18030") from None
    if "\0" in text:
        raise ValueError("Source contains NUL characters")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def chunks(text, limit):
    while len(text) > limit:
        end = text.rfind("\n", limit // 2, limit + 1)
        if end < 0:
            positions = [text.rfind(mark, limit // 2, limit) for mark in ["。", "！", "？", ". ", "! ", "? "]]
            end = max(positions)
            end = end + 1 if end >= 0 else limit
        piece, text = text[:end].strip(), text[end:].strip()
        if piece:
            yield piece
    if text.strip():
        yield text.strip()


def text_sections(text, default_title):
    headings = list(HEADINGS.finditer(text))
    if not headings:
        return [(default_title, text)]
    result = []
    if text[:headings[0].start()].strip():
        result.append(("Opening", text[:headings[0].start()].strip()))
    for i, heading in enumerate(headings):
        end = headings[i+1].start() if i+1 < len(headings) else len(text)
        result.append((heading.group().strip(), text[heading.start():end].strip()))
    return result


class ChapterHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.heading, self.title = [], [], ""
        self.skip, self.in_heading = 0, False

    def handle_starttag(self, tag, attrs):
        if tag in {"head", "script", "style", "noscript"}:
            self.skip += 1
        if self.skip:
            return
        if tag in {"p", "div", "section", "br", "li", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")
        if tag in {"h1", "h2"} and not self.title:
            self.in_heading = True
            self.heading = []

    def handle_endtag(self, tag):
        if tag in {"head", "script", "style", "noscript"}:
            self.skip = max(0, self.skip-1)
            return
        if self.skip:
            return
        if tag in {"h1", "h2"} and self.in_heading:
            self.title = " ".join("".join(self.heading).split())[:200]
            self.in_heading = False
        if tag in {"p", "div", "section", "li", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)
            if self.in_heading:
                self.heading.append(text)

    def text(self):
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line).strip()


def archive_path(base, href):
    parsed = urlsplit(href)
    path = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or parsed.query or not path or "\\" in path or "\0" in path:
        raise ValueError("EPUB content must reference internal archive paths")
    if path.startswith("/") or ".." in path.split("/"):
        raise ValueError("EPUB path traversal is not supported")
    result = posixpath.normpath(posixpath.join(base, path))
    if result.startswith(("/", "../")):
        raise ValueError("EPUB path escapes archive")
    return result


def xml(raw):
    # Decode first so UTF-16 declarations cannot bypass the DTD check.
    text = decode(raw)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("EPUB package XML must not contain DTD or entity declarations")
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        raise ValueError("Invalid EPUB package XML") from None


def epub_sections(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 2048 or len({e.filename for e in entries}) != len(entries):
                raise ValueError("EPUB contains too many or duplicate archive entries")
            if sum(e.file_size for e in entries) > MAX_UNPACKED or any(e.file_size > MAX_FILE for e in entries):
                raise ValueError("EPUB uncompressed size exceeds import limits")
            if any(e.flag_bits & 1 for e in entries) or "META-INF/encryption.xml" in archive.namelist():
                raise ValueError("Encrypted EPUB packages are not supported")

            def read(name):
                try:
                    with archive.open(name) as stream:
                        value = stream.read(MAX_FILE + 1)
                except KeyError:
                    raise ValueError("EPUB references a missing package entry") from None
                if len(value) > MAX_FILE:
                    raise ValueError("EPUB entry exceeds import limits")
                return value

            container = xml(read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None:
                raise ValueError("EPUB is missing its package rootfile")
            package_path = archive_path("", rootfile.get("full-path", ""))
            package = xml(read(package_path))
            manifest = {}
            for item in package.findall("./{*}manifest/{*}item"):
                item_id = item.get("id")
                if not item_id or item_id in manifest:
                    raise ValueError("EPUB manifest IDs must be unique")
                manifest[item_id] = item
            result, total_chars = [], 0
            spine = package.findall("./{*}spine/{*}itemref")
            if len(spine) > 2048 or len({r.get("idref") for r in spine}) != len(spine):
                raise ValueError("EPUB spine contains too many or duplicate references")
            for ref in spine:
                item = manifest.get(ref.get("idref"))
                if item is None:
                    raise ValueError("EPUB spine references an unknown manifest item")
                if item.get("media-type") not in {"application/xhtml+xml", "text/html"}:
                    raise ValueError("EPUB spine must contain HTML text chapters")
                path = archive_path(posixpath.dirname(package_path), item.get("href", ""))
                parser = ChapterHTML()
                parser.feed(decode(read(path)))
                parser.close()
                text = parser.text()
                total_chars += len(text)
                if total_chars > MAX_TEXT:
                    raise ValueError("EPUB text exceeds two million characters")
                if text:
                    result.extend(text_sections(text, parser.title or f"Section {len(result)+1}"))
            if not result:
                raise ValueError("EPUB has no readable text in its spine")
            return result
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError):
        raise ValueError("Invalid or unsupported EPUB archive") from None


class Library:
    def __init__(self, store):
        self.store = store

    def import_book(self, path: Path, title, rights, rights_note="", unit_chars=4000):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise ValueError("Book title must contain 1–200 characters")
        if rights not in {"owned", "licensed", "public-domain"}:
            raise ValueError("Explicit source rights declaration required")
        if not isinstance(rights_note, str) or len(rights_note) > 2000:
            raise ValueError("Rights note must be at most 2000 characters")
        if type(unit_chars) is not int or not 200 <= unit_chars <= 20000:
            raise ValueError("unit_chars must be 200–20000")
        path = Path(path)
        if path.suffix.lower() not in {".txt", ".epub"}:
            raise ValueError("Only TXT and unencrypted EPUB are supported")
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE+1)
        if not 1 <= len(raw) <= MAX_FILE:
            raise ValueError("Source must contain 1 byte–8 MB")
        sections = epub_sections(raw) if path.suffix.lower() == ".epub" else text_sections(decode(raw), title.strip())
        if not sections or sum(len(t) for _, t in sections) > MAX_TEXT:
            raise ValueError("Imported text is empty or exceeds two million characters")
        units = []
        for chapter, (heading, text) in enumerate(sections, 1):
            for part, piece in enumerate(chunks(text, unit_chars), 1):
                units.append({"index": len(units), "chapter": chapter, "part": part,
                              "title": heading, "text": piece, "sha256": sha(piece.encode())})
        if not units or len(units) > 10000:
            raise ValueError("Source must contain 1–10000 readable units")
        book_id = uuid.uuid4().hex
        directory = self.store.root / "library" / book_id
        directory.mkdir(parents=True)
        try:
            (directory / "source.bin").write_bytes(raw)
            with self.store.connect() as db:
                db.execute("INSERT INTO books(id,title,format,source_sha256,rights,rights_note,units) VALUES(?,?,?,?,?,?,?)",
                           (book_id, title.strip(), path.suffix.lower()[1:], sha(raw), rights, rights_note,
                            json.dumps(units, ensure_ascii=False)))
                self.store.event(db, "book_imported", book_id, {"source_sha256": sha(raw), "units": len(units), "rights": rights})
        except Exception:
            shutil.rmtree(directory)
            raise
        return self.inspect(book_id)

    def book(self, book_id):
        identifier(book_id)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not row:
            raise ValueError("Unknown book")
        result = dict(row)
        result["units"] = json.loads(result["units"])
        raw = self.store.root / "library" / book_id / "source.bin"
        if not raw.is_file() or raw.stat().st_size > MAX_FILE or sha(raw.read_bytes()) != result["source_sha256"]:
            raise ValueError("Imported source is missing or changed")
        for unit in result["units"]:
            if sha(unit["text"].encode()) != unit["sha256"]:
                raise ValueError("Imported chapter text changed")
        return result

    def inspect(self, book_id):
        book = self.book(book_id)
        return {**book, "units": [{k: v for k, v in u.items() if k != "text"} for u in book["units"]]}

    def context(self, book_id, unit=0, continuity=""):
        if type(unit) is not int or unit < 0:
            raise ValueError("Unit index must be a nonnegative integer")
        if not isinstance(continuity, str) or len(continuity) > 4000:
            raise ValueError("Continuity notes must be at most 4000 characters")
        book = self.book(book_id)
        if unit >= len(book["units"]):
            raise ValueError("Unit index is outside this book")
        return {"source": {"book_id": book_id, "book_title": book["title"],
                           "source_sha256": book["source_sha256"], "rights": book["rights"],
                           "rights_note": book["rights_note"], **book["units"][unit]},
                "continuity": continuity}

    def validate_context(self, context):
        if not isinstance(context, dict) or "source" not in context:
            raise ValueError("Invalid source context")
        source = context["source"]
        expected = self.context(source["book_id"], source["index"], context.get("continuity", ""))
        if expected["source"] != source:
            raise ValueError("Source snapshot no longer matches the imported book")
        if "character_memory" in context:
            from .story_memory import StoryMemory
            if not isinstance(context.get("series"), dict) or context["character_memory"].get("series") != context["series"].get("id"):
                raise ValueError("Character memory must belong to the planned series")
            memory = StoryMemory(self.store)
            if memory.series(context["series"]["id"])["definition"]["book_id"] != source["book_id"]:
                raise ValueError("Character memory and source book belong to different series")
            memory.validate(context["character_memory"])
        return expected
