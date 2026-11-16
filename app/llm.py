"""A small client for OpenAI-compatible chat APIs (OpenAI, Ollama, LM Studio, Groq, vLLM...)."""
from __future__ import annotations

import json
import logging
from typing import Iterable, Iterator

log = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, detail: str, user_message: str):
        super().__init__(detail)
        self.user_message = user_message


def error_for_status(status: int, body: str) -> LLMError:
    detail = f"HTTP {status}: {body[:300]}"
    if status in (401, 403):
        return LLMError(detail, "The language model service rejected the API key.")
    if status == 404:
        return LLMError(detail, "The language model service doesn't know this model. Check LLM_MODEL.")
    if status == 429:
        return LLMError(detail, "The language model service is rate limiting requests, or the account is out of credit.")
    if status >= 500:
        return LLMError(detail, "The language model service had a problem on its side.")
    return LLMError(detail, f"The language model request failed (HTTP {status}).")


class ThinkFilter:
    """Drops <think>...</think> blocks that reasoning models (for example via Ollama) put in the answer."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        self._started = False

    def feed(self, piece: str) -> str:
        self._buffer += piece
        out = []
        while self._buffer:
            if self._inside:
                end = self._buffer.find(self.CLOSE)
                if end == -1:
                    # keep a possible partial closing tag, drop the rest
                    self._buffer = self._buffer[-(len(self.CLOSE) - 1):]
                    break
                self._buffer = self._buffer[end + len(self.CLOSE):].lstrip()
                self._inside = False
                continue
            start = self._buffer.find(self.OPEN)
            if start == -1:
                keep = _partial_suffix(self._buffer, self.OPEN)
                out.append(self._buffer[: len(self._buffer) - keep])
                self._buffer = self._buffer[len(self._buffer) - keep:]
                break
            out.append(self._buffer[:start])
            self._buffer = self._buffer[start + len(self.OPEN):]
            self._inside = True
        text = "".join(out)
        if not self._started:
            text = text.lstrip()
            self._started = bool(text)
        return text

    def flush(self) -> str:
        text = "" if self._inside else self._buffer
        self._buffer = ""
        return text if self._started else text.lstrip()


def _partial_suffix(text: str, tag: str) -> int:
    """Length of the longest end of ``text`` that could be the start of ``tag``."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0


def parse_stream(lines: Iterable[str]) -> Iterator[str]:
    """Yield the text pieces of a streamed chat completion (server-sent events)."""
    for raw in lines:
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            event = json.loads(data)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("error"):
            raise LLMError(str(event["error"])[:300], "The language model returned an error while answering.")
        for choice in event.get("choices") or []:
            content = (choice.get("delta") or {}).get("content")
            if isinstance(content, str) and content:
                yield content


def strip_think(text: str) -> str:
    f = ThinkFilter()
    return (f.feed(text) + f.flush()).strip()


class ChatModel:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0, client=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        if client is None:
            import httpx

            client = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))
        self._client = client

    @property
    def url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def complete(self, messages: list[dict]) -> str:
        import httpx

        try:
            response = self._client.post(self.url, json={"model": self.model, "messages": messages}, headers=self._headers)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}", "The language model service could not be reached.") from exc
        if response.status_code >= 400:
            raise error_for_status(response.status_code, response.text)
        try:
            content = response.json()["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response: {exc}", "The language model sent a reply this app couldn't read.") from exc
        return strip_think(content)

    def stream(self, messages: list[dict]) -> Iterator[str]:
        import httpx

        payload = {"model": self.model, "messages": messages, "stream": True}
        try:
            with self._client.stream("POST", self.url, json=payload, headers=self._headers) as response:
                if response.status_code >= 400:
                    body = response.read().decode("utf-8", "replace")
                    raise error_for_status(response.status_code, body)
                think = ThinkFilter()
                for piece in parse_stream(response.iter_lines()):
                    text = think.feed(piece)
                    if text:
                        yield text
                tail = think.flush()
                if tail:
                    yield tail
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}", "The language model service could not be reached.") from exc
