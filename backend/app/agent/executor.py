"""Board data acquisition and plan execution.

Owns the path from Monday.com to canonical DataFrames, including caching and
the degradation ladder: live data -> cached data -> stale cached data with a
warning -> an honest error. It never fabricates a frame.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from ..config import get_settings
from ..data import pipeline as pl
from ..models.schemas import AnalysisResult, Board, BoardStatus, QueryPlan
from ..monday.board_resolver import (
    DEALS_COLUMN_ALIASES, DEALS_REQUIRED, WORK_ORDER_COLUMN_ALIASES,
    WORK_ORDERS_REQUIRED, ResolvedBoard, resolve_board,
)
from ..monday.cache import TTLCache, cache_meta
from ..monday.client import MondayAuthError, MondayClient, MondayError
from ..analytics.registry import run_analysis

logger = logging.getLogger(__name__)


@dataclass
class BoardData:
    frame: pd.DataFrame
    report: dict[str, Any]
    status: BoardStatus
    stale: bool = False
    error: str | None = None


@dataclass
class DataBundle:
    deals: pd.DataFrame
    work_orders: pd.DataFrame
    reports: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[BoardStatus] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fatal: str | None = None


class DataService:
    """Fetches, caches and normalizes both boards."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = MondayClient()
        self._items_cache: TTLCache[list[dict]] = TTLCache(settings.monday_cache_ttl_seconds)
        self._resolved: dict[str, ResolvedBoard] = {}

    @property
    def configured(self) -> bool:
        return self._client.configured

    async def _resolve(self, board: Board) -> ResolvedBoard:
        key = board.value
        if key in self._resolved:
            return self._resolved[key]
        settings = get_settings()
        if board == Board.DEALS:
            resolved = await resolve_board(
                self._client,
                explicit_id=settings.monday_deals_board_id,
                board_name=settings.monday_deals_board_name,
                aliases=DEALS_COLUMN_ALIASES,
                required=DEALS_REQUIRED,
            )
        else:
            resolved = await resolve_board(
                self._client,
                explicit_id=settings.monday_work_orders_board_id,
                board_name=settings.monday_work_orders_board_name,
                aliases=WORK_ORDER_COLUMN_ALIASES,
                required=WORK_ORDERS_REQUIRED,
            )
        self._resolved[key] = resolved
        return resolved

    async def load_board(self, board: Board) -> BoardData:
        key = board.value
        if get_settings().data_source == "local_csv":
            return self._load_local(board)
        empty = pl.empty_deals_frame() if board == Board.DEALS else pl.empty_work_orders_frame()
        blank_report = {"board": key, "rows_in": 0, "rows_out": 0,
                        "header_echo_dropped": 0, "injection_suspects": 0, "flags": {}}

        if not self._client.configured:
            return BoardData(
                empty, blank_report,
                BoardStatus(name=key, error="MONDAY_API_TOKEN is not configured"),
                error="Monday.com is not configured. Set MONDAY_API_TOKEN.",
            )

        cached = self._items_cache.get(key)
        stale = False
        error: str | None = None

        if cached is None:
            try:
                resolved = await self._resolve(board)
                items = await self._client.fetch_board_items(resolved.board_id)
                self._items_cache.set(key, items)
                cached = items
            except MondayAuthError as exc:
                return BoardData(empty, blank_report,
                                 BoardStatus(name=key, error=str(exc)),
                                 error=MondayAuthError.user_message)
            except MondayError as exc:
                # Degrade to stale cache rather than failing outright.
                entry = self._items_cache.get_stale(key)
                if entry is None:
                    return BoardData(empty, blank_report,
                                     BoardStatus(name=key, error=str(exc)),
                                     error=getattr(exc, "user_message", str(exc)))
                cached = entry.value
                stale = True
                error = (
                    f"Live data could not be fetched ({exc}); showing data cached "
                    f"{entry.age_seconds}s ago."
                )

        resolved = self._resolved.get(key)
        column_map = resolved.column_map if resolved else {}
        raw = pl.items_to_frame(cached or [], column_map)

        if board == Board.DEALS:
            frame, report = pl.normalize_deals(raw)
        else:
            frame, report = pl.normalize_work_orders(raw)

        meta = cache_meta(self._items_cache.entry(key))
        status = BoardStatus(
            name=resolved.name if resolved else key,
            board_id=resolved.board_id if resolved else None,
            item_count=len(frame),
            fetched_at=meta["fetched_at"],
            age_seconds=meta["age_seconds"],
            error=error,
        )
        if resolved and resolved.missing_fields:
            status.error = (
                (status.error + " ") if status.error else ""
            ) + f"Columns not found on the board: {', '.join(resolved.missing_fields)}."

        return BoardData(frame, report.as_dict(), status, stale=stale, error=error)

    def _load_local(self, board: Board) -> BoardData:
        """Development-only source: the cleaned CSVs in data_clean/.

        This is NOT a stand-in for the Monday integration and is never used
        unless DATA_SOURCE=local_csv is set explicitly. Every response carries a
        visible warning so live and local data can never be confused.
        """
        from .local_source import load_local_board
        return load_local_board(board)

    async def load(self, boards: list[Board]) -> DataBundle:
        wanted = set(boards) or {Board.DEALS}
        bundle = DataBundle(deals=pl.empty_deals_frame(),
                            work_orders=pl.empty_work_orders_frame())

        for board in (Board.DEALS, Board.WORK_ORDERS):
            if board not in wanted:
                continue
            data = await self.load_board(board)
            if board == Board.DEALS:
                bundle.deals = data.frame
            else:
                bundle.work_orders = data.frame
            bundle.reports.append(data.report)
            bundle.statuses.append(data.status)
            if data.error:
                bundle.warnings.append(f"{board.value}: {data.error}")

        both_empty = bundle.deals.empty and bundle.work_orders.empty
        if both_empty and bundle.warnings:
            bundle.fatal = bundle.warnings[0]
        elif both_empty:
            bundle.fatal = (
                "Both Monday.com boards returned no records. They may be empty, or "
                "the token may not have access to them."
            )
        return bundle

    async def board_statuses(self) -> list[BoardStatus]:
        out: list[BoardStatus] = []
        for board in (Board.DEALS, Board.WORK_ORDERS):
            data = await self.load_board(board)
            out.append(data.status)
        return out



def execute(plan: QueryPlan, bundle: DataBundle, today: date | None = None) -> AnalysisResult:
    result = run_analysis(plan, bundle.deals, bundle.work_orders, bundle.reports, today)
    for warning in bundle.warnings:
        if warning not in result.ledger.warnings:
            result.ledger.warnings.append(warning)
    return result
