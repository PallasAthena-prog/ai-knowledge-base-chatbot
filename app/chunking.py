"""Split page text into overlapping, sentence-aligned chunks.

Chunks never cross a page, so every chunk has one exact page number, and each
chunk keeps its sentence offsets for sentence-level highlighting later on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .textproc import Span, heading_text, limit_span_length, split_sentences


@dataclass
class Chunk:
    page_no: int
    ordinal: int
    start: int
    end: int
    text: str
    heading: str | None
    # [start, end, is_heading] for every sentence, as offsets into the page text
    sentences: list[list[int]] = field(default_factory=list)


def chunk_pages(pages: list[str], chunk_size: int = 900, overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading: str | None = None
    for page_no, text in enumerate(pages, start=1):
        spans = limit_span_length(text, split_sentences(text), chunk_size)
        heading = _chunk_page(text, page_no, spans, chunk_size, overlap, heading, chunks)
    return chunks


def _chunk_page(
    text: str,
    page_no: int,
    spans: list[Span],
    chunk_size: int,
    overlap: int,
    heading: str | None,
    out: list[Chunk],
) -> str | None:
    current: list[int] = []
    chunk_heading = heading

    def emit() -> None:
        if not current or all(spans[i].heading for i in current):
            return
        first, last = spans[current[0]], spans[current[-1]]
        out.append(
            Chunk(
                page_no=page_no,
                ordinal=len(out),
                start=first.start,
                end=last.end,
                text=text[first.start:last.end],
                heading=chunk_heading,
                sentences=[[spans[i].start, spans[i].end, int(spans[i].heading)] for i in current],
            )
        )

    def tail_for_overlap() -> list[int]:
        """The last sentences of the chunk that fit in ``overlap`` characters, never all of them.

        The final sentence is always repeated when it isn't too long, so neighbouring chunks share context.
        """
        if overlap <= 0:
            return []
        tail: list[int] = []
        for i in reversed(current[1:]):
            size = spans[current[-1]].end - spans[i].start
            if spans[i].heading or (size > overlap and (tail or size > chunk_size * 0.4)):
                break
            tail.insert(0, i)
        return tail

    for idx, span in enumerate(spans):
        if span.heading:
            size = spans[current[-1]].end - spans[current[0]].start if current else 0
            has_body = any(not spans[i].heading for i in current)
            if has_body and size >= chunk_size * 0.35:
                emit()
                current = []
            heading = heading_text(text[span.start:span.end])
            if not any(not spans[i].heading for i in current):
                chunk_heading = heading
            current.append(idx)
            continue
        if current and span.end - spans[current[0]].start > chunk_size:
            emit()
            current = tail_for_overlap()
            while current and span.end - spans[current[0]].start > chunk_size:
                current.pop(0)
            chunk_heading = heading
        if not current:
            chunk_heading = heading
        current.append(idx)
    emit()
    return heading
