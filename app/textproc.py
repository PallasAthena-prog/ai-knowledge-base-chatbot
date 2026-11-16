"""Text helpers: cleanup, sentence spans, search terms.

Everything here works on character offsets into the original page text, so a
sentence found during chunking can later be highlighted in the exact same place.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing done down during
    each either few for from further get gets got had has have having he her here hers
    herself him himself his how i if in into is it its itself just let me might more most
    much must my myself need no nor not now of off on once only or other our ours
    ourselves out over own per please same shall she should so some such tell than that
    the their theirs them themselves then there these they this those through to too
    under until up upon us very via was we were what when where which while who whom
    whose why will with within without would you your yours yourself yourselves
    """.split()
)

ABBREVIATIONS = frozenset(
    "e.g i.e etc vs mr mrs ms dr prof st no nos approx incl dept fig ref inc ltd co jr sr min max am pm".split()
)

WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦‣]|\d{1,2}[.)]|[a-z][.)])\s+")
MD_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+\S")
_BOUNDARY_RE = re.compile(r"[.!?]+[\"'”’)\]]*\s+")
_TERMINAL = ".!?:;,"


def normalize_text(text: str) -> str:
    """Clean extracted text without changing its meaning."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "").replace(" ", " ").replace("\t", " ")
    text = text.replace("​", "").replace("﻿", "")
    # words broken across lines: "employ-\nment" -> "employment"
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)
    text = re.sub(r"[ ]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t.lower().replace("’", "'") for t in WORD_RE.findall(text)]


def content_terms(text: str) -> list[str]:
    """Lower-cased words without stopwords, used for keyword search and matching."""
    out = []
    for token in tokens(text):
        if token in STOPWORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        out.append(token)
    return out


def stem(word: str) -> str:
    """A deliberately small stemmer, enough to match 'days' with 'day' or 'reported' with 'report'."""
    if word.isdigit() or len(word) <= 3:
        return word
    if word.endswith("'s"):
        word = word[:-2]
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("es") and len(word) > 4 and word[-3] in "sxz":
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def stemmed_terms(text: str) -> set[str]:
    return {stem(t) for t in content_terms(text)}


def heading_text(text: str) -> str:
    """'## Paid time off' -> 'Paid time off'."""
    return collapse_ws(re.sub(r"^\s{0,3}#{1,6}\s+", "", text))


_DANGLING = frozenset(
    "the a an and or of to in on for with from by at as is are be that than your our their this these those "
    "we you will can must may not".split()
)


def looks_like_heading(line: str, previous: str | None = None, following: str | None = None) -> bool:
    """Guess whether a line of extracted text is a section heading."""
    stripped = line.strip()
    if not stripped:
        return False
    if MD_HEADING_RE.match(stripped):
        return True
    if len(stripped) > 70 or stripped[-1] in _TERMINAL:
        return False
    words = stripped.split()
    if len(words) > 10 or not (stripped[0].isupper() or stripped[0].isdigit()):
        return False
    if stripped[0].isdigit() and not re.match(r"^\d+(\.\d+)*\.?\s+[A-Z]", stripped):
        return False
    # A line ending in "the", "and", "from"... is a sentence that wraps onto the next line.
    if words[-1].lower() in _DANGLING:
        return False
    # A heading follows a finished paragraph and isn't continued in lower case on the next line.
    if previous is not None and previous.strip() and previous.strip()[-1] not in ".!?:":
        return False
    if following and following.strip()[:1].islower():
        return False
    return True


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    heading: bool = False


def split_sentences(text: str) -> list[Span]:
    """Split text into sentence spans (offsets into ``text``). Headings become their own span."""
    spans: list[Span] = []
    for seg in _segments(text):
        if seg.heading:
            spans.append(seg)
        else:
            spans.extend(_split_segment(text, seg.start, seg.end))
    return spans


def _segments(text: str) -> list[Span]:
    """Group lines into paragraphs, list items and headings."""
    segments: list[Span] = []
    cur_start: int | None = None
    cur_end = 0
    previous: str | None = None
    pos = 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        start, end = pos, pos + len(line)
        pos = end + 1
        stripped = line.strip()
        following = lines[index + 1] if index + 1 < len(lines) else None
        if not stripped:
            if cur_start is not None:
                segments.append(Span(cur_start, cur_end))
                cur_start = None
            previous = None
            continue
        lead = len(line) - len(line.lstrip())
        line_start, line_end = start + lead, start + len(line.rstrip())
        if looks_like_heading(line, previous, following):
            if cur_start is not None:
                segments.append(Span(cur_start, cur_end))
                cur_start = None
            segments.append(Span(line_start, line_end, heading=True))
            previous = "."  # whatever follows a heading starts fresh
            continue
        if BULLET_RE.match(line) and cur_start is not None:
            segments.append(Span(cur_start, cur_end))
            cur_start = None
        if cur_start is None:
            cur_start = line_start
        cur_end = line_end
        previous = line
    if cur_start is not None:
        segments.append(Span(cur_start, cur_end))
    return segments


def _split_segment(text: str, seg_start: int, seg_end: int) -> list[Span]:
    seg = text[seg_start:seg_end]
    out: list[Span] = []
    start = 0
    for match in _BOUNDARY_RE.finditer(seg):
        nxt = match.end()
        if nxt >= len(seg):
            break
        following = seg[nxt]
        if not (following.isupper() or following.isdigit() or following in "\"'“‘([" or BULLET_RE.match(seg[nxt:nxt + 4])):
            continue
        before = seg[start:match.start()]
        last = re.search(r"([^\s(\[\"']+)$", before)
        word = last.group(1).lower().rstrip(".") if last else ""
        if word in ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
            continue
        end = match.start() + len(match.group().rstrip())
        if seg[start:end].strip():
            out.append(Span(seg_start + start, seg_start + end))
        start = nxt
    if seg[start:].strip():
        out.append(Span(seg_start + start, seg_end))
    return out


def limit_span_length(text: str, spans: list[Span], max_len: int) -> list[Span]:
    """Cut sentences that are longer than ``max_len`` at whitespace (tables, run-on lines)."""
    out: list[Span] = []
    for span in spans:
        start = span.start
        while span.end - start > max_len:
            cut = text.rfind(" ", start + max_len // 2, start + max_len)
            if cut == -1:
                cut = start + max_len
            out.append(Span(start, cut, span.heading))
            start = cut
            while start < span.end and text[start].isspace():
                start += 1
        if start < span.end:
            out.append(Span(start, span.end, span.heading))
    return out


def shorten(text: str, limit: int) -> str:
    text = collapse_ws(text)
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > limit // 2 else limit].rstrip(" ,;:") + "..."
