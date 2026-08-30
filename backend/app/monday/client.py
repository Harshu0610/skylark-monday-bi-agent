"""Monday.com GraphQL client. Queries only -- never mutations.

Handles the four things that actually go wrong against this API: pagination,
rate limits / complexity budgets, transient 5xx, and expired tokens. Each maps
to a distinct, actionable error rather than a generic failure.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..config import get_settings
from . import queries

logger = logging.getLogger(__name__)


class MondayError(Exception):
    """Base class for Monday integration failures."""

    user_message = "I couldn't retrieve data from Monday.com."


class MondayAuthError(MondayError):
    """Token missing, invalid, or expired. Never retried -- retrying cannot help."""

    user_message = (
        "Monday.com rejected the API token. Check MONDAY_API_TOKEN in your environment."
    )


class MondayRateLimitError(MondayError):
    user_message = "Monday.com is rate limiting requests. Please try again shortly."


class MondayBoardNotFoundError(MondayError):
    user_message = "The expected Monday.com board could not be found."


class MondayUnavailableError(MondayError):
    user_message = (
        "Monday.com is not responding right now. Please try again in a moment."
    )


class MondayClient:
    def __init__(self, token: str | None = None) -> None:
        settings = get_settings()
        self._token = token if token is not None else settings.monday_api_token
        self._url = settings.monday_api_url
        self._version = settings.monday_api_version
        self._timeout = settings.monday_timeout_seconds
        self._page_size = settings.monday_page_size

    @property
    def configured(self) -> bool:
        return bool(self._token)

    # -- transport ---------------------------------------------------------

    async def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        attempt: int = 1,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if not self._token:
            raise MondayAuthError("MONDAY_API_TOKEN is not set")

        headers = {
            "Authorization": self._token,
            "Content-Type": "application/json",
            "API-Version": self._version,
        }
        payload = {"query": query, "variables": variables or {}}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt < max_attempts:
                await asyncio.sleep(2 ** (attempt - 1))
                return await self._execute(
                    query, variables, attempt=attempt + 1, max_attempts=max_attempts
                )
            raise MondayUnavailableError(f"transport failure: {exc}") from exc

        if response.status_code in (401, 403):
            raise MondayAuthError(f"HTTP {response.status_code} from Monday.com")

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 2 ** attempt))
            if attempt < max_attempts:
                logger.warning("monday rate limited, retrying in %.1fs", retry_after)
                await asyncio.sleep(min(retry_after, 10.0))
                return await self._execute(
                    query, variables, attempt=attempt + 1, max_attempts=max_attempts
                )
            raise MondayRateLimitError("rate limited after retries")

        if response.status_code >= 500:
            if attempt < max_attempts:
                await asyncio.sleep(2 ** (attempt - 1))
                return await self._execute(
                    query, variables, attempt=attempt + 1, max_attempts=max_attempts
                )
            raise MondayUnavailableError(f"HTTP {response.status_code}")

        if response.status_code != 200:
            raise MondayError(f"HTTP {response.status_code}: {response.text[:200]}")

        body = response.json()

        # Monday returns 200 with an errors array for GraphQL-level problems,
        # including the complexity budget -- so status code alone is not enough.
        if "errors" in body and body["errors"]:
            messages = "; ".join(
                str(e.get("message", e)) for e in body["errors"][:3]
            )
            lowered = messages.lower()
            if "complexity" in lowered or "rate limit" in lowered:
                if attempt < max_attempts:
                    await asyncio.sleep(5 * attempt)
                    return await self._execute(
                        query, variables, attempt=attempt + 1, max_attempts=max_attempts
                    )
                raise MondayRateLimitError(messages)
            if "unauthor" in lowered or "authentication" in lowered:
                raise MondayAuthError(messages)
            raise MondayError(messages)

        data = body.get("data")
        if data is None:
            raise MondayError("Monday.com returned no data")
        return data

    # -- reads -------------------------------------------------------------

    async def list_boards(self, limit: int = 100) -> list[dict[str, Any]]:
        data = await self._execute(queries.LIST_BOARDS, {"limit": limit})
        return data.get("boards") or []

    async def get_board_columns(self, board_id: str) -> dict[str, Any]:
        data = await self._execute(queries.BOARD_COLUMNS, {"boardId": [str(board_id)]})
        boards = data.get("boards") or []
        if not boards:
            raise MondayBoardNotFoundError(f"board {board_id} not found")
        return boards[0]

    async def fetch_board_items(self, board_id: str) -> list[dict[str, Any]]:
        """Fetch every item on a board, following the cursor to exhaustion."""
        data = await self._execute(
            queries.BOARD_ITEMS_FIRST_PAGE,
            {"boardId": [str(board_id)], "limit": self._page_size},
        )
        boards = data.get("boards") or []
        if not boards:
            raise MondayBoardNotFoundError(f"board {board_id} not found")

        page = boards[0].get("items_page") or {}
        items: list[dict[str, Any]] = list(page.get("items") or [])
        cursor = page.get("cursor")

        # Bounded so a cursor bug cannot spin forever.
        max_pages = 100
        pages = 1
        while cursor and pages < max_pages:
            data = await self._execute(
                queries.BOARD_ITEMS_NEXT_PAGE,
                {"cursor": cursor, "limit": self._page_size},
            )
            page = data.get("next_items_page") or {}
            batch = page.get("items") or []
            items.extend(batch)
            cursor = page.get("cursor")
            pages += 1
            if not batch:
                break

        logger.info("fetched %d items from board %s (%d pages)", len(items), board_id, pages)
        return items
