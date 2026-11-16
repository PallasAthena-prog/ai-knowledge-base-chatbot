"""Hybrid retrieval: BM25 keyword search and vector search, merged with reciprocal rank fusion."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from .store import Store
from .textproc import content_terms, shorten

log = logging.getLogger(__name__)


@dataclass
class Source:
    n: int
    chunk_id: int
    document_id: str
    title: str
    file_type: str
    page_no: int
    page_count: int
    heading: str | None
    text: str
    char_start: int
    char_end: int
    sentences: list[list[int]]
    keyword_rank: int | None
    semantic_rank: int | None
    score: float

    def sentence_texts(self, include_headings: bool = False) -> list[tuple[int, str]]:
        """(index, text) for each sentence of the chunk."""
        out = []
        for i, (start, end, is_heading) in enumerate(self.sentences):
            if is_heading and not include_headings:
                continue
            out.append((i, self.text[start - self.char_start:end - self.char_start]))
        return out

    def label(self) -> str:
        if self.file_type == "pdf":
            return f"{self.title}, page {self.page_no}"
        if self.heading:
            return f'{self.title}, section "{self.heading}"'
        return self.title

    def public(self) -> dict:
        return {
            "n": self.n,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "file_type": self.file_type,
            "page_no": self.page_no,
            "page_count": self.page_count,
            "heading": self.heading,
            "snippet": shorten(self.text, 260),
            "ranges": [[self.char_start, self.char_end]],
            "quotes": [text for _, text in self.sentence_texts()] or [self.text],
            "keyword_rank": self.keyword_rank,
            "semantic_rank": self.semantic_rank,
        }


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


class VectorIndex:
    """All chunk embeddings in one matrix, reloaded when the documents change."""

    def __init__(self, store: Store):
        self.store = store
        self._lock = threading.Lock()
        self._version = -1
        # (ids, doc_codes, doc_index, matrix), replaced as a whole so readers never see a mix
        self._snapshot = None

    def _refresh(self):
        import numpy as np

        with self._lock:
            if self._version == self.store.version and self._snapshot is not None:
                return self._snapshot
            version = self.store.version
            doc_index: dict[str, int] = {}
            ids, codes, vectors = [], [], []
            for chunk_id, doc_id, blob in self.store.load_embeddings():
                vector = np.frombuffer(blob, dtype=np.float32)
                if vectors and vector.shape != vectors[0].shape:
                    continue  # left over from a different model; the startup check re-embeds those
                ids.append(chunk_id)
                codes.append(doc_index.setdefault(doc_id, len(doc_index)))
                vectors.append(vector)
            self._snapshot = (
                np.asarray(ids, dtype=np.int64),
                np.asarray(codes, dtype=np.int64),
                doc_index,
                np.vstack(vectors) if vectors else np.zeros((0, 0), dtype=np.float32),
            )
            self._version = version
            return self._snapshot

    def search(self, query_vector, doc_ids: list[str] | None, limit: int) -> list[tuple[int, float]]:
        import numpy as np

        ids, codes, doc_index, matrix = self._refresh()
        if not len(ids) or matrix.shape[1] != len(query_vector):
            return []
        scores = matrix @ np.asarray(query_vector, dtype=np.float32)
        if doc_ids is not None:
            wanted = [doc_index[d] for d in doc_ids if d in doc_index]
            if not wanted:
                return []
            scores = np.where(np.isin(codes, wanted), scores, -np.inf)
        k = min(limit, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(ids[i]), float(scores[i])) for i in top if np.isfinite(scores[i])]


class Retriever:
    def __init__(self, store: Store, embedder=None, top_k: int = 6, candidates: int = 24, min_semantic: float = 0.25):
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.candidates = candidates
        self.min_semantic = min_semantic
        self.vectors = VectorIndex(store) if embedder is not None else None

    @property
    def mode(self) -> str:
        return "hybrid" if self.embedder is not None else "keyword"

    def search(self, query: str, doc_ids: list[str] | None = None, top_k: int | None = None) -> list[Source]:
        if doc_ids is not None and not doc_ids:
            return []
        top_k = top_k or self.top_k
        keyword = self.store.keyword_search(content_terms(query), doc_ids, self.candidates)

        semantic: list[tuple[int, float]] = []
        if self.embedder is not None and self.vectors is not None:
            try:
                vector = self.embedder.embed_query(query)
                semantic = [
                    pair for pair in self.vectors.search(vector, doc_ids, self.candidates)
                    if pair[1] >= self.min_semantic
                ]
            except Exception:
                log.exception("Vector search failed, using keyword results only")

        keyword_rank = {cid: i for i, (cid, _) in enumerate(keyword, start=1)}
        semantic_rank = {cid: i for i, (cid, _) in enumerate(semantic, start=1)}
        fused = reciprocal_rank_fusion([[cid for cid, _ in keyword], [cid for cid, _ in semantic]])[:top_k]
        rows = self.store.get_chunks(cid for cid, _ in fused)

        allowed = set(doc_ids) if doc_ids is not None else None
        sources: list[Source] = []
        for chunk_id, score in fused:
            row = rows.get(chunk_id)
            if row is None or (allowed is not None and row["document_id"] not in allowed):
                continue
            sources.append(
                Source(
                    n=len(sources) + 1,
                    chunk_id=chunk_id,
                    document_id=row["document_id"],
                    title=row["title"],
                    file_type=row["file_type"],
                    page_no=row["page_no"],
                    page_count=row["page_count"],
                    heading=row["heading"],
                    text=row["text"],
                    char_start=row["char_start"],
                    char_end=row["char_end"],
                    sentences=row["sentences"],
                    keyword_rank=keyword_rank.get(chunk_id),
                    semantic_rank=semantic_rank.get(chunk_id),
                    score=round(score, 5),
                )
            )
        return sources
