"""Shared test helpers (plain functions, so the tests also run without pytest fixtures)."""
from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.service import SAMPLES_DIR, KnowledgeBase
from app.store import Store

FAQ = SAMPLES_DIR / "Northwind-Product-FAQ.md"
POLICY = SAMPLES_DIR / "Northwind-IT-Security-Policy.docx"
HANDBOOK = SAMPLES_DIR / "Northwind-Employee-Handbook.pdf"


def make_kb(tmp: Path, chat_model=None, **env) -> KnowledgeBase:
    values = {"DATA_DIR": str(tmp), "EMBEDDINGS": "off", "LLM_BASE_URL": "", **env}
    settings = Settings.from_env(values)
    return KnowledgeBase(settings, Store(settings.db_path), chat_model=chat_model)


class FakeChat:
    """Stands in for the language model client."""

    def __init__(self, pieces=None, rewrite="", fail_after=None):
        self.pieces = pieces or []
        self.rewrite = rewrite
        self.fail_after = fail_after
        self.calls = []

    def complete(self, messages):
        self.calls.append(("complete", messages))
        return self.rewrite

    def stream(self, messages):
        from app.llm import LLMError

        self.calls.append(("stream", messages))
        for i, piece in enumerate(self.pieces):
            if self.fail_after is not None and i == self.fail_after:
                raise LLMError("boom", "The language model service had a problem on its side.")
            yield piece
