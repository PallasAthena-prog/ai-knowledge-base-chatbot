"""Turn uploaded files into page text. PDF uses pypdf; Word, Markdown and text use the standard library."""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .textproc import normalize_text

SUPPORTED_TYPES = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".markdown": "md", ".txt": "txt"}
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_XML_BYTES = 60 * 1024 * 1024


class ParseError(Exception):
    """Raised with a message that can be shown to the person who uploaded the file."""


@dataclass
class ParsedDocument:
    title: str
    file_type: str
    pages: list[str]


def file_type_for(filename: str) -> str | None:
    return SUPPORTED_TYPES.get(Path(filename).suffix.lower())


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    title = re.sub(r"[-_]+", " ", stem)
    return re.sub(r"\s+", " ", title).strip() or "Untitled document"


def parse_file(path: Path, filename: str, max_pages: int = 500) -> ParsedDocument:
    file_type = file_type_for(filename)
    if file_type is None:
        raise ParseError("Only PDF, Word (.docx), Markdown and text files are supported.")
    if file_type == "pdf":
        title, pages = _parse_pdf(path, max_pages)
    elif file_type == "docx":
        title, pages = _parse_docx(path)
    else:
        title, pages = _parse_text(path, markdown=file_type == "md")
    return ParsedDocument(title=title or title_from_filename(filename), file_type=file_type, pages=pages)


# --- PDF ---------------------------------------------------------------------------------------

def _parse_pdf(path: Path, max_pages: int) -> tuple[str | None, list[str]]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import DependencyError
    except ImportError as exc:  # pragma: no cover - pypdf is in requirements.txt
        raise ParseError("PDF support needs the pypdf package.") from exc

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except DependencyError:
                raise
            except Exception:
                unlocked = 0
            if not unlocked:
                raise ParseError("This PDF is password protected.")
        count = len(reader.pages)
        if count > max_pages:
            raise ParseError(f"This PDF has {count} pages. The limit is {max_pages}.")
        pages, failures = [], 0
        for page in reader.pages:
            try:
                raw = page.extract_text() or ""
            except DependencyError:
                raise
            except Exception:
                raw, failures = "", failures + 1
            pages.append(normalize_text(raw))
        if count and failures == count:
            raise ParseError("The text of this PDF could not be extracted.")
        title = None
        try:
            meta_title = reader.metadata.title if reader.metadata else None
        except Exception:
            meta_title = None
        if isinstance(meta_title, str):
            meta_title = meta_title.strip()
            if 3 <= len(meta_title) <= 150 and not meta_title.lower().startswith(("microsoft word", "untitled")):
                title = meta_title
    except ParseError:
        raise
    except DependencyError as exc:
        raise ParseError("This PDF is encrypted and needs the 'cryptography' package to be read.") from exc
    except Exception as exc:
        raise ParseError("This PDF could not be read. It may be damaged.") from exc
    return title, strip_repeated_lines(pages)


def strip_repeated_lines(pages: list[str]) -> list[str]:
    """Remove running headers and footers such as 'Company handbook | Page 3 of 9'."""
    if len(pages) < 3:
        return pages

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    edge_lines = []
    for text in pages:
        lines = [ln for ln in text.split("\n") if ln.strip()]
        edge_lines.append({key(ln) for ln in lines[:2] + lines[-2:]})
    counts = Counter(k for keys in edge_lines for k in keys)
    threshold = max(3, int(len(pages) * 0.6))
    repeated = {k for k, n in counts.items() if n >= threshold and len(k) <= 120}
    if not repeated:
        return pages

    cleaned = []
    for text in pages:
        lines = text.split("\n")
        filled = [i for i, ln in enumerate(lines) if ln.strip()]
        edges = set(filled[:2] + filled[-2:])
        kept = [ln for i, ln in enumerate(lines) if not (i in edges and key(ln) in repeated)]
        cleaned.append("\n".join(kept).strip())
    return cleaned


# --- Word --------------------------------------------------------------------------------------

def _read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise ParseError("This Word file is too large to read.")
    data = zf.read(name)
    # Word never uses a DTD; refusing one rules out entity expansion tricks.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ParseError("This Word file contains unsupported XML.")
    return ET.fromstring(data)


def _parse_docx(path: Path) -> tuple[str | None, list[str]]:
    try:
        with zipfile.ZipFile(path) as zf:
            document = _read_xml(zf, "word/document.xml")
            styles = _read_xml(zf, "word/styles.xml")
            core = _read_xml(zf, "docProps/core.xml")
    except ParseError:
        raise
    except (zipfile.BadZipFile, ET.ParseError, OSError) as exc:
        raise ParseError("This Word file could not be read. It may be damaged.") from exc
    if document is None:
        raise ParseError("This file is not a Word document.")

    style_names: dict[str, str] = {}
    if styles is not None:
        for style in styles.iter(f"{W}style"):
            style_id = style.get(f"{W}styleId")
            name = style.find(f"{W}name")
            if style_id and name is not None:
                style_names[style_id] = (name.get(f"{W}val") or "").lower()

    body = document.find(f"{W}body")
    blocks: list[str] = []
    first_heading = None
    if body is not None:
        for kind, text in _walk_body(body, style_names):
            if not text.strip():
                continue
            if kind.startswith("h") and first_heading is None:
                first_heading = text.lstrip("# ").strip()
            blocks.append(text)

    title = None
    if core is not None:
        node = core.find(f"{DC}title")
        if node is not None and node.text and node.text.strip():
            title = node.text.strip()
    page = normalize_text("\n\n".join(blocks))
    return title or first_heading, [page]


def _walk_body(parent: ET.Element, style_names: dict[str, str]):
    for el in parent:
        if el.tag == f"{W}p":
            yield _paragraph(el, style_names)
        elif el.tag == f"{W}tbl":
            yield "table", _table(el)
        elif el.tag == f"{W}sdt":
            content = el.find(f"{W}sdtContent")
            if content is not None:
                yield from _walk_body(content, style_names)


def _paragraph_text(p: ET.Element) -> str:
    parts = []
    for node in p.iter():
        if node.tag == f"{W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{W}tab":
            parts.append(" ")
        elif node.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
        elif node.tag == f"{W}noBreakHyphen":
            parts.append("-")
    return "".join(parts).strip()


def _paragraph(p: ET.Element, style_names: dict[str, str]) -> tuple[str, str]:
    text = _paragraph_text(p)
    ppr = p.find(f"{W}pPr")
    style_id, level, is_list = "", None, False
    if ppr is not None:
        style = ppr.find(f"{W}pStyle")
        if style is not None:
            style_id = style.get(f"{W}val") or ""
        outline = ppr.find(f"{W}outlineLvl")
        if outline is not None and (outline.get(f"{W}val") or "").isdigit():
            level = int(outline.get(f"{W}val")) + 1
        is_list = ppr.find(f"{W}numPr") is not None
    name = style_names.get(style_id, style_id.lower())
    match = re.match(r"heading\s*(\d)", name)
    if match:
        level = int(match.group(1))
    elif name == "title":
        level = 1
    if "list" in name:
        is_list = True
    if level and 1 <= level <= 6 and text and "\n" not in text:
        return f"h{level}", "#" * level + " " + text
    if is_list and text:
        text = re.sub(r"^[•▪◦\-*]\s*", "", text)
        return "list", "- " + text
    return "p", text


def _table(tbl: ET.Element) -> str:
    rows = []
    for tr in tbl.iter(f"{W}tr"):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            cell = " ".join(_paragraph_text(p) for p in tc.iter(f"{W}p")).strip()
            cells.append(re.sub(r"\s+", " ", cell))
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


# --- Markdown and plain text ---------------------------------------------------------------------

def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _parse_text(path: Path, markdown: bool) -> tuple[str | None, list[str]]:
    text = normalize_text(_decode(path.read_bytes()))
    title = None
    if markdown:
        match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        if match:
            title = match.group(1).strip()
    return title, [text]
