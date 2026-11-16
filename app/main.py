"""HTTP API and static frontend."""
from __future__ import annotations

import hmac
import json
import logging
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import BASE_DIR, get_settings
from .parsers import MEDIA_TYPES, ParseError, file_type_for
from .service import KnowledgeBase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

STATIC_DIR = BASE_DIR / "static"
DOC_ID_RE = re.compile(r"^[0-9a-f]{32}$")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    kb = await run_in_threadpool(KnowledgeBase.create, settings)
    if settings.load_sample_docs:
        added = await run_in_threadpool(kb.load_samples)
        if added:
            log.info("Loaded %d sample documents", added)
    app.state.kb = kb
    health = kb.health()
    log.info(
        "Ready: answers=%s, search=%s",
        health["llm"]["model"] or "quotes only",
        health["retrieval"]["mode"],
    )
    yield


MAX_FILES_PER_UPLOAD = 20


def token_ok(value: str | None) -> bool:
    return not settings.admin_token or hmac.compare_digest((value or "").encode(), settings.admin_token.encode())


class UploadGuard:
    """Checks the admin token and the declared size of an upload before its body is read.

    FastAPI parses multipart forms before running dependencies, so without this an
    unauthorised or oversized upload would be written to disk before it is refused.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/api/documents":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            limit = settings.max_upload_mb * 1024 * 1024 * MAX_FILES_PER_UPLOAD + 1024 * 1024
            length = headers.get("content-length", "")
            problem = None
            if not token_ok(headers.get("x-admin-token")):
                problem = (401, "This action needs the admin token.")
            elif length.isdigit() and int(length) > limit:
                problem = (413, "The upload is too large.")
            if problem:
                response = JSONResponse({"detail": problem[1]}, status_code=problem[0])
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


app = FastAPI(title="Knowledge Base Chatbot", version=__version__, lifespan=lifespan)
app.add_middleware(UploadGuard)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def kb() -> KnowledgeBase:
    return app.state.kb


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not token_ok(x_admin_token):
        raise HTTPException(status_code=401, detail="This action needs the admin token.")


def document_or_404(doc_id: str) -> dict:
    doc = kb().store.get_document(doc_id) if DOC_ID_RE.match(doc_id) else None
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


# --- pages -----------------------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    return FileResponse(STATIC_DIR / "demo.html")


@app.get("/widget.js", include_in_schema=False)
def widget() -> FileResponse:
    return FileResponse(STATIC_DIR / "widget.js", media_type="application/javascript")


# --- API -------------------------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return kb().health()


@app.get("/api/stats")
def stats() -> dict:
    return kb().store.stats()


@app.get("/api/documents")
def list_documents() -> dict:
    return {"documents": kb().store.list_documents()}


async def save_upload(upload: UploadFile, target: Path, limit: int) -> None:
    size = 0
    with target.open("wb") as out:
        while block := await upload.read(1024 * 1024):
            size += len(block)
            if size > limit:
                raise ParseError(f"The file is larger than {limit // (1024 * 1024)} MB.")
            out.write(block)
    if size == 0:
        raise ParseError("The file is empty.")


@app.post("/api/documents", dependencies=[Depends(require_admin)])
async def upload_documents(files: list[UploadFile] = File(...)) -> dict:
    limit = settings.max_upload_mb * 1024 * 1024
    results = []
    for upload in files[:MAX_FILES_PER_UPLOAD]:
        filename = Path(upload.filename or "upload").name
        if file_type_for(filename) is None:
            results.append({"filename": filename, "error": "Only PDF, Word (.docx), Markdown and text files are supported."})
            continue
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"upload{Path(filename).suffix.lower()}"
            try:
                await save_upload(upload, path, limit)
                doc, created = await run_in_threadpool(kb().ingest_file, path, filename)
                results.append({"filename": filename, "document": doc, "duplicate": not created})
            except ParseError as exc:
                results.append({"filename": filename, "error": str(exc)})
            except Exception:
                log.exception("Upload of %s failed", filename)
                results.append({"filename": filename, "error": "Something went wrong while indexing this file."})
            finally:
                await upload.close()
    return {"results": results}


@app.delete("/api/documents/{doc_id}", dependencies=[Depends(require_admin)])
def delete_document(doc_id: str) -> dict:
    doc = document_or_404(doc_id)
    kb().delete_document(doc["id"])
    return {"deleted": doc["id"]}


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: str) -> FileResponse:
    doc = document_or_404(doc_id)
    path = kb().file_path(doc)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The original file is missing.")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(doc["file_type"], "application/octet-stream"),
        filename=doc["filename"],
        content_disposition_type="inline",
    )


@app.get("/api/documents/{doc_id}/pages/{page_no}")
def document_page(doc_id: str, page_no: int) -> dict:
    doc = document_or_404(doc_id)
    text = kb().store.get_page(doc["id"], page_no)
    if text is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    return {"document_id": doc["id"], "page_no": page_no, "page_count": doc["page_count"], "text": text}


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=200_000)  # only the end of the history is used, cut to 2,000 characters


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=100)
    document_ids: list[str] | None = Field(default=None, max_length=10_000)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    question = request.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="The question is empty.")
    doc_ids = None
    if request.document_ids is not None:
        doc_ids = [d for d in dict.fromkeys(request.document_ids) if DOC_ID_RE.match(d)]
    history = [item.model_dump() for item in request.history[-12:]]
    events = kb().answer(question, history, doc_ids)

    def body():
        try:
            for event, data in events:
                yield sse(event, data)
        except Exception:
            log.exception("Chat request failed")
            yield sse("error", {"message": "Something went wrong while answering. Please try again."})

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class FeedbackRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(max_length=20000)
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


@app.post("/api/feedback")
def feedback(request: FeedbackRequest) -> dict:
    kb().store.add_feedback(request.question, request.answer, request.rating, request.comment)
    return {"ok": True}
