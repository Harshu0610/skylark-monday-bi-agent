"""Provider-abstracted LLM access.

Three providers behind one interface so the same code runs on a free hosted
tier (Groq), a paid API (Anthropic), or a local model (Ollama) during offline
development. Switching is an env var, not a code change -- which also means the
demo has a second provider to fall back to if one is rate limited.
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete_json(
        self, system: str, user: str, *, schema_hint: str, max_tokens: int = 1200
    ) -> dict[str, Any]:
        """Return a JSON object. Implementations must raise LLMError on failure."""

    @abstractmethod
    async def complete_text(
        self, system: str, user: str, *, max_tokens: int = 900, temperature: float = 0.3
    ) -> str:
        ...


# ---------------------------------------------------------------------------
# JSON extraction shared by all providers
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response.

    Smaller models wrap JSON in prose or code fences even when told not to, so
    this is defensive by design rather than optimistic.
    """
    if not text:
        raise LLMError("empty response from model")

    candidates: list[str] = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise LLMError(f"could not parse JSON from model output: {text[:200]}")


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------

class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self) -> None:
        s = get_settings()
        self._key = s.groq_api_key
        self._model = s.groq_model
        self._timeout = s.llm_timeout_seconds

    async def _chat(self, messages: list[dict], *, max_tokens: int,
                    temperature: float, json_mode: bool) -> str:
        if not self._key:
            raise LLMError("GROQ_API_KEY is not set")
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._key}"},
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"groq transport failure: {exc}") from exc

        if r.status_code == 401:
            raise LLMError("Groq rejected the API key")
        if r.status_code == 429:
            raise LLMError("Groq rate limit reached")
        if r.status_code >= 400:
            raise LLMError(f"groq HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"unexpected groq response shape: {exc}") from exc

    async def complete_json(self, system, user, *, schema_hint, max_tokens=1200):
        content = await self._chat(
            [
                {"role": "system", "content": f"{system}\n\n{schema_hint}"},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens, temperature=0.0, json_mode=True,
        )
        return extract_json(content)

    async def complete_text(self, system, user, *, max_tokens=900, temperature=0.3):
        return await self._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=temperature, json_mode=False,
        )


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        s = get_settings()
        self._key = s.anthropic_api_key
        self._model = s.anthropic_model
        self._timeout = s.llm_timeout_seconds

    async def _message(self, system: str, user: str, *, max_tokens: int,
                       temperature: float) -> str:
        if not self._key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    json={
                        "model": self._model,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                    },
                    headers={
                        "x-api-key": self._key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic transport failure: {exc}") from exc

        if r.status_code == 401:
            raise LLMError("Anthropic rejected the API key")
        if r.status_code == 429:
            raise LLMError("Anthropic rate limit reached")
        if r.status_code >= 400:
            raise LLMError(f"anthropic HTTP {r.status_code}: {r.text[:200]}")
        try:
            blocks = r.json()["content"]
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, ValueError) as exc:
            raise LLMError(f"unexpected anthropic response shape: {exc}") from exc

    async def complete_json(self, system, user, *, schema_hint, max_tokens=1200):
        text = await self._message(
            f"{system}\n\n{schema_hint}\n\nRespond with a single JSON object and nothing else.",
            user, max_tokens=max_tokens, temperature=0.0,
        )
        return extract_json(text)

    async def complete_text(self, system, user, *, max_tokens=900, temperature=0.3):
        return await self._message(system, user, max_tokens=max_tokens,
                                   temperature=temperature)


# ---------------------------------------------------------------------------
# Ollama (local development)
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self) -> None:
        s = get_settings()
        self._base = s.ollama_base_url.rstrip("/")
        self._model = s.ollama_model
        self._timeout = max(s.llm_timeout_seconds, 120.0)  # CPU inference is slow

    async def _generate(self, system: str, user: str, *, json_mode: bool,
                        temperature: float) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "system": system,
            "prompt": user,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(f"{self._base}/api/generate", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(
                f"could not reach Ollama at {self._base}. Is it running? ({exc})"
            ) from exc
        if r.status_code >= 400:
            raise LLMError(f"ollama HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("response", "")

    async def complete_json(self, system, user, *, schema_hint, max_tokens=1200):
        text = await self._generate(f"{system}\n\n{schema_hint}", user,
                                    json_mode=True, temperature=0.0)
        return extract_json(text)

    async def complete_text(self, system, user, *, max_tokens=900, temperature=0.3):
        return await self._generate(system, user, json_mode=False,
                                    temperature=temperature)


_PROVIDERS = {
    "groq": GroqProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}


def get_provider() -> LLMProvider:
    settings = get_settings()
    factory = _PROVIDERS.get(settings.llm_provider)
    if factory is None:
        raise LLMError(f"unknown LLM provider '{settings.llm_provider}'")
    return factory()
