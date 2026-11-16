"""SQLite storage: documents, page text, chunks with a full-text index, query log and feedback."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = """
create table if not exists documents (
  id          text primary key,
  filename    text not null,
  title       text not null,
  file_type   text not null,
  size_bytes  integer not null,
  sha256      text not null unique,
  page_count  integer not null,
  chunk_count integer not null,
  char_count  integer not null,
  is_sample   integer not null default 0,
  note        text,
  created_at  text not null
);

create table if not exists pages (
  document_id text not null references documents(id) on delete cascade,
  page_no     integer not null,
  text        text not null,
  primary key (document_id, page_no)
);

create table if not exists chunks (
  id          integer primary key,
  document_id text not null references documents(id) on delete cascade,
  page_no     integer not null,
  ordinal     integer not null,
  heading     text,
  char_start  integer not null,
  char_end    integer not null,
  text        text not null,
  search_text text not null,
  sentences   text not null,
  embedding   blob
);
create index if not exists chunks_by_document on chunks(document_id, ordinal);

create virtual table if not exists chunks_fts using fts5(
  search_text, heading,
  content='chunks', content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2'
);

create trigger if not exists chunks_fts_insert after insert on chunks begin
  insert into chunks_fts(rowid, search_text, heading) values (new.id, new.search_text, new.heading);
end;
create trigger if not exists chunks_fts_delete after delete on chunks begin
  insert into chunks_fts(chunks_fts, rowid, search_text, heading)
  values ('delete', old.id, old.search_text, old.heading);
end;
create trigger if not exists chunks_fts_update after update of search_text, heading on chunks begin
  insert into chunks_fts(chunks_fts, rowid, search_text, heading)
  values ('delete', old.id, old.search_text, old.heading);
  insert into chunks_fts(rowid, search_text, heading) values (new.id, new.search_text, new.heading);
end;

create table if not exists meta (
  key   text primary key,
  value text not null
);

create table if not exists queries (
  id           integer primary key,
  question     text not null,
  search_query text not null,
  mode         text not null,
  source_count integer not null,
  latency_ms   integer not null,
  created_at   text not null
);

create table if not exists feedback (
  id         integer primary key,
  question   text not null,
  answer     text not null,
  rating     integer not null check (rating in (-1, 1)),
  comment    text,
  created_at text not null
);
"""

DOC_COLUMNS = (
    "id, filename, title, file_type, size_bytes, page_count, chunk_count, char_count, is_sample, note, created_at"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        # bumped whenever documents change, so in-memory caches know to reload
        self.version = 0
        with self.connect() as conn:
            conn.execute("pragma journal_mode = wal")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connect() as conn:
            yield conn

    # --- documents --------------------------------------------------------------------------

    def find_by_sha(self, sha256: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(f"select {DOC_COLUMNS} from documents where sha256 = ?", (sha256,)).fetchone()
        return dict(row) if row else None

    def add_document(self, doc: dict, pages: list[str], chunks: list[dict]) -> None:
        with self.writing() as conn:
            conn.execute(
                "insert into documents (id, filename, title, file_type, size_bytes, sha256, page_count,"
                " chunk_count, char_count, is_sample, note, created_at)"
                " values (:id, :filename, :title, :file_type, :size_bytes, :sha256, :page_count,"
                " :chunk_count, :char_count, :is_sample, :note, :created_at)",
                doc,
            )
            conn.executemany(
                "insert into pages (document_id, page_no, text) values (?, ?, ?)",
                [(doc["id"], i, text) for i, text in enumerate(pages, start=1)],
            )
            conn.executemany(
                "insert into chunks (document_id, page_no, ordinal, heading, char_start, char_end, text,"
                " search_text, sentences, embedding) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        doc["id"], c["page_no"], c["ordinal"], c["heading"], c["start"], c["end"],
                        c["text"], c["search_text"], json.dumps(c["sentences"]), c.get("embedding"),
                    )
                    for c in chunks
                ],
            )
        self.version += 1

    def list_documents(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(f"select {DOC_COLUMNS} from documents order by created_at, title").fetchall()
        return [dict(r) for r in rows]

    def get_document(self, doc_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(f"select {DOC_COLUMNS} from documents where id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def delete_document(self, doc_id: str) -> bool:
        with self.writing() as conn:
            # delete chunks explicitly so the full-text trigger runs for every row
            conn.execute("delete from chunks where document_id = ?", (doc_id,))
            conn.execute("delete from pages where document_id = ?", (doc_id,))
            deleted = conn.execute("delete from documents where id = ?", (doc_id,)).rowcount
        self.version += 1
        return bool(deleted)

    def get_page(self, doc_id: str, page_no: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "select text from pages where document_id = ? and page_no = ?", (doc_id, page_no)
            ).fetchone()
        return row["text"] if row else None

    # --- search ------------------------------------------------------------------------------

    def keyword_search(self, terms: list[str], doc_ids: list[str] | None, limit: int) -> list[tuple[int, float]]:
        """BM25 search over chunk text and headings. Terms are plain words, OR-ed together."""
        if not terms or doc_ids == []:
            return []
        query = " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))
        sql = (
            "select c.id, bm25(chunks_fts, 1.0, 0.5) as score"
            " from chunks_fts join chunks c on c.id = chunks_fts.rowid"
            " where chunks_fts match ?"
        )
        params: list = [query]
        if doc_ids is not None:
            sql += f" and c.document_id in ({','.join('?' * len(doc_ids))})"
            params.extend(doc_ids)
        sql += " order by score limit ?"
        params.append(limit)
        with self.connect() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        # bm25() is lower-is-better; flip it so higher means more relevant
        return [(r["id"], -float(r["score"])) for r in rows]

    def get_chunks(self, ids: Iterable[int]) -> dict[int, dict]:
        ids = list(ids)
        if not ids:
            return {}
        sql = (
            "select c.id, c.document_id, c.page_no, c.heading, c.char_start, c.char_end, c.text, c.sentences,"
            " d.title, d.file_type, d.page_count"
            " from chunks c join documents d on d.id = c.document_id"
            f" where c.id in ({','.join('?' * len(ids))})"
        )
        with self.connect() as conn:
            rows = conn.execute(sql, ids).fetchall()
        out = {}
        for r in rows:
            item = dict(r)
            item["sentences"] = json.loads(item["sentences"])
            out[item["id"]] = item
        return out

    def load_embeddings(self) -> list[tuple[int, str, bytes]]:
        with self.connect() as conn:
            rows = conn.execute(
                "select id, document_id, embedding from chunks where embedding is not null order by id"
            ).fetchall()
        return [(r["id"], r["document_id"], r["embedding"]) for r in rows]

    def chunks_for_embedding(self, only_missing: bool) -> list[dict]:
        sql = (
            "select c.id, c.heading, c.search_text, d.title from chunks c join documents d on d.id = c.document_id"
        )
        if only_missing:
            sql += " where c.embedding is null"
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql + " order by c.id").fetchall()]

    def set_embeddings(self, pairs: list[tuple[bytes | None, int]]) -> None:
        with self.writing() as conn:
            conn.executemany("update chunks set embedding = ? where id = ?", pairs)
        self.version += 1

    def clear_embeddings(self) -> None:
        with self.writing() as conn:
            conn.execute("update chunks set embedding = null")
        self.version += 1

    def clear_note(self, note: str) -> None:
        with self.writing() as conn:
            conn.execute("update documents set note = null where note = ?", (note,))

    # --- meta, logs, stats -------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("select value from meta where key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.writing() as conn:
            conn.execute(
                "insert into meta (key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                (key, value),
            )

    def log_query(self, question: str, search_query: str, mode: str, source_count: int, latency_ms: int) -> None:
        with self.writing() as conn:
            conn.execute(
                "insert into queries (question, search_query, mode, source_count, latency_ms, created_at)"
                " values (?, ?, ?, ?, ?, ?)",
                (question, search_query, mode, source_count, latency_ms, now_iso()),
            )

    def add_feedback(self, question: str, answer: str, rating: int, comment: str | None) -> None:
        with self.writing() as conn:
            conn.execute(
                "insert into feedback (question, answer, rating, comment, created_at) values (?, ?, ?, ?, ?)",
                (question, answer, rating, comment, now_iso()),
            )

    def stats(self) -> dict:
        with self.connect() as conn:
            docs = conn.execute(
                "select count(*) as n, coalesce(sum(size_bytes), 0) as size, coalesce(sum(page_count), 0) as pages"
                " from documents"
            ).fetchone()
            chunks = conn.execute("select count(*) as n from chunks").fetchone()["n"]
            questions = conn.execute("select count(*) as n from queries").fetchone()["n"]
            fb = conn.execute(
                "select coalesce(sum(rating = 1), 0) as up, coalesce(sum(rating = -1), 0) as down from feedback"
            ).fetchone()
        return {
            "documents": docs["n"],
            "pages": docs["pages"],
            "storage_bytes": docs["size"],
            "chunks": chunks,
            "questions": questions,
            "feedback_up": fb["up"],
            "feedback_down": fb["down"],
        }
