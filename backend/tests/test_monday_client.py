"""Monday.com integration tests against a mocked transport.

Covers the four things that actually go wrong in production: pagination,
expired tokens, rate limits, and boards or columns that aren't where we expect.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.monday.board_resolver import (
    DEALS_COLUMN_ALIASES, WORK_ORDER_COLUMN_ALIASES, build_column_map, resolve_board,
)
from app.monday.cache import TTLCache
from app.monday.client import (
    MondayAuthError, MondayBoardNotFoundError, MondayClient,
    MondayRateLimitError, MondayUnavailableError,
)
from app.data.pipeline import item_to_record, items_to_frame




@pytest.fixture
def patch_httpx(monkeypatch):
    def _apply(handler):
        transport = httpx.MockTransport(handler)
        original_init = httpx.AsyncClient.__init__

        def init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    return _apply


def _json(payload: dict, status: int = 200, headers: dict | None = None):
    return httpx.Response(status, json=payload, headers=headers or {})


def _item(item_id: str, name: str, values: dict[str, str]):
    return {
        "id": item_id,
        "name": name,
        "column_values": [
            {"id": k, "text": v, "value": json.dumps(v), "type": "text"}
            for k, v in values.items()
        ],
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_follows_the_cursor_to_exhaustion(patch_httpx):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _json({"data": {"boards": [{
                "id": "1", "name": "Deals",
                "items_page": {"cursor": "c1", "items": [_item("i1", "Alpha", {})]},
            }]}})
        if calls["n"] == 2:
            return _json({"data": {"next_items_page": {
                "cursor": "c2", "items": [_item("i2", "Beta", {})]}}})
        return _json({"data": {"next_items_page": {
            "cursor": None, "items": [_item("i3", "Gamma", {})]}}})

    patch_httpx(handler)
    items = await MondayClient(token="t").fetch_board_items("1")
    assert [i["name"] for i in items] == ["Alpha", "Beta", "Gamma"]
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_empty_board_is_not_an_error(patch_httpx):
    patch_httpx(lambda r: _json({"data": {"boards": [
        {"id": "1", "name": "Deals", "items_page": {"cursor": None, "items": []}}
    ]}}))
    items = await MondayClient(token="t").fetch_board_items("1")
    assert items == []


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_token_raises_auth_error_and_is_not_retried(patch_httpx):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"errors": ["unauthorized"]})

    patch_httpx(handler)
    with pytest.raises(MondayAuthError):
        await MondayClient(token="bad").fetch_board_items("1")
    assert calls["n"] == 1  # retrying an invalid token cannot help


@pytest.mark.asyncio
async def test_missing_token_fails_before_any_request():
    with pytest.raises(MondayAuthError):
        await MondayClient(token="").fetch_board_items("1")


@pytest.mark.asyncio
async def test_rate_limit_is_retried_then_surfaced(patch_httpx):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"error": "rate limit"},
                              headers={"Retry-After": "0"})

    patch_httpx(handler)
    with pytest.raises(MondayRateLimitError):
        await MondayClient(token="t").fetch_board_items("1")
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_server_error_is_retried_then_surfaced(patch_httpx):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(502, text="bad gateway")

    patch_httpx(handler)
    with pytest.raises(MondayUnavailableError):
        await MondayClient(token="t").fetch_board_items("1")
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_graphql_errors_returned_with_http_200_are_detected(patch_httpx):
    """Monday returns 200 with an errors array, so status code alone is not enough."""
    patch_httpx(lambda r: _json({"errors": [{"message": "Field 'nope' doesn't exist"}]}))
    with pytest.raises(Exception) as exc:
        await MondayClient(token="t").fetch_board_items("1")
    assert "nope" in str(exc.value)


@pytest.mark.asyncio
async def test_board_not_found_lists_what_is_available(patch_httpx):
    patch_httpx(lambda r: _json({"data": {"boards": [
        {"id": "9", "name": "Marketing Tasks", "items_count": 3}]}}))
    with pytest.raises(MondayBoardNotFoundError) as exc:
        await resolve_board(
            MondayClient(token="t"), explicit_id=None, board_name="Deals",
            aliases=DEALS_COLUMN_ALIASES, required=[],
        )
    assert "Marketing Tasks" in str(exc.value)


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------

def test_column_map_matches_the_real_board_titles():
    columns = [
        {"id": "text1", "title": "Deal Name", "type": "text"},
        {"id": "status1", "title": "Deal Status", "type": "status"},
        {"id": "status2", "title": "Deal Stage", "type": "status"},
        {"id": "dropdown1", "title": "Sector/service", "type": "dropdown"},
        {"id": "numbers1", "title": "Masked Deal value", "type": "numbers"},
    ]
    mapping, missing = build_column_map(columns, DEALS_COLUMN_ALIASES)
    assert mapping["amount"] == "numbers1"
    assert mapping["sector"] == "dropdown1"
    assert "probability" in missing


def test_column_map_survives_a_renamed_column():
    """Someone renames 'Masked Deal value' to 'Deal Value'. The app keeps working."""
    columns = [{"id": "n1", "title": "Deal Value", "type": "numbers"}]
    mapping, _ = build_column_map(columns, DEALS_COLUMN_ALIASES)
    assert mapping["amount"] == "n1"


def test_column_matching_ignores_case_spacing_and_punctuation():
    columns = [{"id": "s1", "title": "  execution   STATUS ", "type": "status"}]
    mapping, _ = build_column_map(columns, WORK_ORDER_COLUMN_ALIASES)
    assert mapping["exec_status"] == "s1"


def test_missing_columns_are_reported_not_silently_dropped():
    mapping, missing = build_column_map([], DEALS_COLUMN_ALIASES)
    assert mapping == {}
    assert "amount" in missing and "sector" in missing


# ---------------------------------------------------------------------------
# Item unpacking
# ---------------------------------------------------------------------------

def test_item_name_is_used_when_the_title_column_is_absent():
    item = _item("i1", "Scooby-Doo", {"status1": "Open"})
    record = item_to_record(item, {"status": "status1"})
    assert record["deal_name"] == "Scooby-Doo"
    assert record["status"] == "Open"


def test_unmapped_columns_become_none_rather_than_missing_keys():
    item = _item("i1", "Alpha", {})
    record = item_to_record(item, {"amount": "does_not_exist"})
    assert record["amount"] is None


def test_items_to_frame_produces_one_row_per_item():
    items = [_item("1", "A", {"c": "x"}), _item("2", "B", {"c": "y"})]
    frame = items_to_frame(items, {"sector": "c"})
    assert len(frame) == 2
    assert list(frame["sector"]) == ["x", "y"]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_cache_returns_value_within_ttl_and_expires_after():
    cache: TTLCache[str] = TTLCache(ttl_seconds=60)
    cache.set("deals", "payload")
    assert cache.get("deals") == "payload"

    cache._store["deals"].stored_at -= 120
    assert cache.get("deals") is None


def test_expired_entry_is_still_available_as_stale():
    """When Monday is unreachable, clearly-labelled stale data beats no answer."""
    cache: TTLCache[str] = TTLCache(ttl_seconds=60)
    cache.set("deals", "payload")
    cache._store["deals"].stored_at -= 300

    assert cache.get("deals") is None
    stale = cache.get_stale("deals")
    assert stale is not None and stale.value == "payload"
    assert stale.age_seconds >= 300
