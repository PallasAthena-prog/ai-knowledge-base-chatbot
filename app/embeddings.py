"""Text embeddings for semantic search: a local ONNX model (default) or an OpenAI-compatible API."""
from __future__ import annotations

import logging
import threading
from typing import Protocol

import numpy as np

from .config import Settings

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class LocalEmbedder:
    """Runs a small sentence embedding model on the CPU with fastembed. No API key needed."""

    def __init__(self, model_name: str, cache_dir: str):
        from fastembed import TextEmbedding

        self.name = f"local:{model_name}"
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        with self._lock:
            vectors = list(self._model.passage_embed(texts))
        return _normalize(np.vstack(vectors))

    def embed_query(self, text: str) -> np.ndarray:
        with self._lock:
            vector = next(iter(self._model.query_embed(text)))
        return _normalize(np.asarray(vector, dtype=np.float32)[None, :])[0]


class ApiEmbedder:
    """Calls the /embeddings endpoint of an OpenAI-compatible server (OpenAI, Ollama, LM Studio...)."""

    batch_size = 64

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        import httpx

        self.name = f"api:{model}"
        self._url = f"{base_url}/embeddings"
        self._model = model
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(timeout=timeout)

    def _embed(self, inputs: list[str]) -> np.ndarray:
        response = self._client.post(self._url, json={"model": self._model, "input": inputs}, headers=self._headers)
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return np.asarray([item["embedding"] for item in data], dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        parts = [self._embed(texts[i:i + self.batch_size]) for i in range(0, len(texts), self.batch_size)]
        return _normalize(np.vstack(parts))

    def embed_query(self, text: str) -> np.ndarray:
        return _normalize(self._embed([text]))[0]


def create_embedder(settings: Settings) -> tuple[Embedder | None, str | None]:
    """Return (embedder, problem). Without an embedder the app falls back to keyword search."""
    if settings.embeddings == "off":
        return None, None
    try:
        if settings.embeddings == "api":
            if not settings.embedding_base_url:
                return None, "EMBEDDINGS=api needs EMBEDDING_BASE_URL or LLM_BASE_URL"
            embedder = ApiEmbedder(
                settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model, settings.llm_timeout
            )
            embedder.embed_query("connection check")
            return embedder, None
        settings.embedding_cache_dir.mkdir(parents=True, exist_ok=True)
        return LocalEmbedder(settings.embedding_model, str(settings.embedding_cache_dir)), None
    except Exception as exc:  # missing package, no network for the first download, bad key...
        log.warning("Semantic search is off, keyword search only: %s", exc)
        return None, f"{type(exc).__name__}: {exc}"


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()
