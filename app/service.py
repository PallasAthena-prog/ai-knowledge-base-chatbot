"""The knowledge base: ingestion, retrieval and answering, independent of the web framework."""
from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator

from .answer import (
    NO_RESULTS,
    build_messages,
    clean_rewrite,
    extractive_answer,
    finalize_answer,
    heuristic_query,
    rewrite_messages,
)
from .chunking import chunk_pages
from .config import BASE_DIR, Settings
from .llm import ChatModel, LLMError
from .parsers import ParseError, file_type_for, parse_file
from .search import Retriever
from .store import Store, now_iso
from .textproc import collapse_ws, heading_text

log = logging.getLogger(__name__)

SAMPLES_DIR = BASE_DIR / "samples"
EMBED_BATCH = 64
NO_TEXT_NOTE = "No text found. Scanned PDFs need OCR before they can be searched."
NO_VECTORS_NOTE = "Semantic search is unavailable for this file; keyword search still works."


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def search_text(text: str) -> str:
    """Chunk text as it goes into the search index: markdown heading marks removed, whitespace collapsed."""
    lines = [heading_text(ln) if ln.lstrip().startswith("#") else ln for ln in text.split("\n")]
    return collapse_ws(" ".join(lines))


class KnowledgeBase:
    def __init__(self, settings: Settings, store: Store, embedder=None, chat_model=None, embedder_problem=None):
        self.settings = settings
        self.store = store
        self.embedder = embedder
        self.embedder_problem = embedder_problem
        self.chat_model = chat_model
        self.retriever = Retriever(
            store, embedder, top_k=settings.top_k, min_semantic=settings.semantic_min_score
        )
        self._ingest_lock = threading.Lock()
        settings.files_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, settings: Settings) -> "KnowledgeBase":
        store = Store(settings.db_path)
        embedder, problem = None, None
        if settings.embeddings != "off":
            from .embeddings import create_embedder

            embedder, problem = create_embedder(settings)
        chat_model = None
        if settings.llm_enabled:
            chat_model = ChatModel(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout)
        kb = cls(settings, store, embedder, chat_model, problem)
        kb.sync_embeddings()
        return kb

    # --- status -------------------------------------------------------------------------------

    def health(self) -> dict:
        docs = self.store.list_documents()
        return {
            "status": "ok",
            "assistant_name": self.settings.assistant_name,
            "company_name": self.settings.company_name,
            "llm": {
                "enabled": self.chat_model is not None,
                "model": self.settings.llm_model if self.chat_model else None,
            },
            "retrieval": {
                "mode": self.retriever.mode,
                "embedding_model": self.embedder.name if self.embedder else None,
                "problem": self.embedder_problem,
            },
            "documents": len(docs),
            "samples_loaded": any(d["is_sample"] for d in docs),
            "suggestions": list(self.settings.suggested_questions),
            "uploads_need_token": bool(self.settings.admin_token),
            "max_upload_mb": self.settings.max_upload_mb,
        }

    # --- ingestion ----------------------------------------------------------------------------

    def ingest_file(self, path: Path, filename: str, is_sample: bool = False) -> tuple[dict, bool]:
        """Index one file. Returns (document, created). The file at ``path`` is copied, not moved."""
        file_type = file_type_for(filename)
        if file_type is None:
            raise ParseError("Only PDF, Word (.docx), Markdown and text files are supported.")
        with self._ingest_lock:
            sha = sha256_file(path)
            existing = self.store.find_by_sha(sha)
            if existing and existing["chunk_count"] > 0:
                return existing, False
            if existing:
                # an earlier upload produced no text (for example before OCR); index it again
                self.delete_document(existing["id"])

            parsed = parse_file(path, filename, self.settings.max_pages)
            chunks = chunk_pages(parsed.pages, self.settings.chunk_size, self.settings.chunk_overlap)
            rows = [
                {
                    "page_no": c.page_no,
                    "ordinal": c.ordinal,
                    "heading": c.heading,
                    "start": c.start,
                    "end": c.end,
                    "text": c.text,
                    "search_text": search_text(c.text),
                    "sentences": c.sentences,
                }
                for c in chunks
            ]
            note = None
            if not rows:
                note = NO_TEXT_NOTE
            elif self.embedder is not None:
                try:
                    texts = [self._embedding_text(parsed.title, r["heading"], r["search_text"]) for r in rows]
                    for start in range(0, len(texts), EMBED_BATCH):
                        vectors = self.embedder.embed_passages(texts[start:start + EMBED_BATCH])
                        for row, vector in zip(rows[start:start + EMBED_BATCH], vectors):
                            row["embedding"] = vector.astype("float32").tobytes()
                except Exception:
                    log.exception("Embedding %s failed; it is still searchable by keyword", filename)
                    for row in rows:
                        row.pop("embedding", None)
                    note = NO_VECTORS_NOTE

            doc_id = uuid.uuid4().hex
            suffix = Path(filename).suffix.lower()
            stored = self.settings.files_dir / f"{doc_id}{suffix}"
            shutil.copyfile(path, stored)
            name = Path(filename).name
            if len(name) > 255:  # shorten the name but keep the extension, which file_path() relies on
                name = Path(name).stem[: 255 - len(suffix)] + suffix
            doc = {
                "id": doc_id,
                "filename": name,
                "title": parsed.title[:200],
                "file_type": parsed.file_type,
                "size_bytes": stored.stat().st_size,
                "sha256": sha,
                "page_count": len(parsed.pages),
                "chunk_count": len(rows),
                "char_count": sum(len(p) for p in parsed.pages),
                "is_sample": int(is_sample),
                "note": note,
                "created_at": now_iso(),
            }
            try:
                self.store.add_document(doc, parsed.pages, rows)
            except Exception:
                stored.unlink(missing_ok=True)
                raise
            doc.pop("sha256")
            return doc, True

    @staticmethod
    def _embedding_text(title: str, heading: str | None, text: str) -> str:
        return "\n".join(part for part in (title, heading, text) if part)

    def delete_document(self, doc_id: str) -> bool:
        doc = self.store.get_document(doc_id)
        if doc is None:
            return False
        self.store.delete_document(doc_id)
        self.file_path(doc).unlink(missing_ok=True)
        return True

    def file_path(self, doc: dict) -> Path:
        return self.settings.files_dir / f"{doc['id']}{Path(doc['filename']).suffix.lower()}"

    def load_samples(self) -> int:
        """Index the demo documents once, on the very first start."""
        if self.store.get_meta("samples_loaded") or not SAMPLES_DIR.is_dir():
            return 0
        added = 0
        for path in sorted(SAMPLES_DIR.iterdir()):
            if path.is_file() and file_type_for(path.name):
                try:
                    _, created = self.ingest_file(path, path.name, is_sample=True)
                    added += int(created)
                except Exception:
                    log.exception("Could not load sample %s", path.name)
        self.store.set_meta("samples_loaded", now_iso())
        return added

    def sync_embeddings(self) -> None:
        """Embed chunks that have no vector yet, or all of them after a model change."""
        if self.embedder is None:
            return
        if self.store.get_meta("embedding_model") != self.embedder.name:
            # vectors from two different models can't be compared, so start from scratch
            self.store.clear_embeddings()
            self.store.set_meta("embedding_model", self.embedder.name)
        rows = self.store.chunks_for_embedding(only_missing=True)
        if not rows:
            return
        log.info("Embedding %d chunks with %s", len(rows), self.embedder.name)
        try:
            for start in range(0, len(rows), EMBED_BATCH):
                batch = rows[start:start + EMBED_BATCH]
                vectors = self.embedder.embed_passages(
                    [self._embedding_text(r["title"], r["heading"], r["search_text"]) for r in batch]
                )
                self.store.set_embeddings([(v.astype("float32").tobytes(), r["id"]) for v, r in zip(vectors, batch)])
        except Exception as exc:
            log.exception("Embedding failed; those chunks are found by keyword search only")
            self.embedder_problem = f"Some passages have no vectors yet ({type(exc).__name__}). Restart to retry."
            return
        self.store.clear_note(NO_VECTORS_NOTE)

    # --- answering ----------------------------------------------------------------------------

    def search_query(self, question: str, history: list[dict]) -> str:
        if not history:
            return question
        if self.chat_model is not None and self.settings.query_rewrite:
            try:
                rewritten = self.chat_model.complete(rewrite_messages(question, history))
                return clean_rewrite(rewritten, question)
            except LLMError as exc:
                log.warning("Query rewrite failed: %s", exc)
        return heuristic_query(question, history)

    def answer(self, question: str, history: list[dict], doc_ids: list[str] | None) -> Iterator[tuple[str, dict]]:
        """Yield (event, data) pairs: status, sources, delta, notice, reset and finally final."""
        started = time.monotonic()
        yield "status", {"stage": "searching"}
        query = self.search_query(question, history)
        sources = self.retriever.search(query, doc_ids)
        yield "sources", {"query": query, "sources": [s.public() for s in sources]}

        mode = "none"
        if not sources:
            markdown, citations = NO_RESULTS, []
        elif self.chat_model is None:
            markdown, citations = extractive_answer(question, sources)
            mode = "quotes"
        else:
            yield "status", {"stage": "writing"}
            messages = build_messages(
                question, sources, history, self.settings.assistant_name, self.settings.company_name
            )
            parts: list[str] = []
            try:
                for piece in self.chat_model.stream(messages):
                    parts.append(piece)
                    yield "delta", {"text": piece}
                text = "".join(parts).strip()
                if not text:
                    raise LLMError("empty answer", "The language model sent an empty answer.")
                markdown, citations = finalize_answer(text, sources)
                mode = "llm"
            except LLMError as exc:
                log.warning("Answer generation failed: %s", exc)
                if parts:
                    yield "reset", {}
                yield "notice", {"message": f"{exc.user_message} Showing the matching passages instead."}
                markdown, citations = extractive_answer(question, sources)
                mode = "quotes"

        latency = int((time.monotonic() - started) * 1000)
        try:
            self.store.log_query(question, query, mode, len(sources), latency)
        except Exception:
            log.exception("Could not log the query")
        yield "final", {
            "markdown": markdown,
            "citations": citations,
            "mode": mode,
            "model": self.settings.llm_model if mode == "llm" else None,
            "latency_ms": latency,
        }
