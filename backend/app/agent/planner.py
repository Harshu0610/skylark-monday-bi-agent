"""Question -> QueryPlan.

The planner sees the user's question and NOTHING ELSE. No board data reaches it,
which is what makes prompt injection through Monday.com content structurally
unable to influence what the system decides to do.

Every field it produces is validated against the enums in schemas.py. The model
cannot invent an intent, a metric or a board; an unrecognised value falls back
to a safe default rather than propagating into the analytics layer.
"""
from __future__ import annotations

import logging
from typing import Any

from ..llm.base import LLMError, LLMProvider
from ..models.schemas import (
    Board, ChatTurn, DatePreset, DateRange, Filters, Intent, QueryPlan,
)
from . import fallback
from .prompts import PLANNER_SCHEMA_HINT, PLANNER_SYSTEM

logger = logging.getLogger(__name__)


class PlanOutcome:
    def __init__(
        self,
        plan: QueryPlan | None,
        *,
        clarification: str | None = None,
        degraded: bool = False,
        degraded_reason: str | None = None,
    ) -> None:
        self.plan = plan
        self.clarification = clarification
        self.degraded = degraded
        self.degraded_reason = degraded_reason


def _coerce_enum(raw: Any, enum_cls, default=None):
    if raw is None:
        return default
    try:
        return enum_cls(str(raw).strip().lower())
    except ValueError:
        logger.warning("planner produced unknown %s: %r", enum_cls.__name__, raw)
        return default


def _coerce_filters(raw: Any) -> Filters:
    if not isinstance(raw, dict):
        return Filters()

    date_range = None
    dr = raw.get("date_range")
    if isinstance(dr, dict):
        preset = _coerce_enum(dr.get("preset"), DatePreset, None)
        start, end = dr.get("start"), dr.get("end")
        if preset or start or end:
            try:
                date_range = DateRange(preset=preset, start=start or None, end=end or None)
            except Exception:  # noqa: BLE001 - a bad date must not kill the request
                date_range = DateRange(preset=preset) if preset else None

    def _str(key: str) -> str | None:
        v = raw.get(key)
        return str(v).strip() if v not in (None, "", "null") else None

    def _list(key: str) -> list[str]:
        v = raw.get(key)
        return [str(i) for i in v if i] if isinstance(v, list) else []

    return Filters(
        sector=_str("sector"),
        owner=_str("owner"),
        account=_str("account"),
        status=_list("status"),
        stage=_list("stage"),
        nature_of_work=_str("nature_of_work"),
        date_range=date_range,
    )


def _boards_for(intent: Intent, raw: Any) -> list[Board]:
    boards: list[Board] = []
    if isinstance(raw, list):
        for item in raw:
            board = _coerce_enum(item, Board, None)
            if board and board not in boards:
                boards.append(board)
    if boards:
        return boards
    # The intent always implies the boards, so a bad list is recoverable.
    return fallback.keyword_plan("").boards if False else _default_boards(intent)


def _default_boards(intent: Intent) -> list[Board]:
    if intent in (Intent.WORK_ORDER_STATUS, Intent.DELIVERY_PERFORMANCE,
                  Intent.DELAYED_WORK, Intent.BILLING_RISK):
        return [Board.WORK_ORDERS]
    if intent == Intent.PERIOD_COMPARISON:
        return [Board.DEALS]
    if intent in (Intent.CROSS_BOARD_SECTOR, Intent.CROSS_BOARD_ACCOUNT,
                  Intent.EXECUTIVE_SUMMARY, Intent.LEADERSHIP_UPDATE,
                  Intent.DATA_QUALITY):
        return [Board.DEALS, Board.WORK_ORDERS]
    return [Board.DEALS]


def parse_plan(payload: dict[str, Any], question: str) -> PlanOutcome:
    if payload.get("needs_clarification") and payload.get("clarification_question"):
        return PlanOutcome(None, clarification=str(payload["clarification_question"]))

    intent = _coerce_enum(payload.get("intent"), Intent, None)
    if intent is None:
        # The model named an intent we do not implement. Keyword routing gives a
        # sane answer instead of an error.
        logger.warning("planner returned unusable intent %r", payload.get("intent"))
        plan = fallback.keyword_plan(question)
        plan.assumptions.append(
            "The question did not map cleanly onto a known analysis, so it was "
            "routed by keyword."
        )
        return PlanOutcome(plan, degraded=True, degraded_reason="unrecognised intent")

    assumptions = payload.get("assumptions")
    assumptions = [str(a) for a in assumptions if a] if isinstance(assumptions, list) else []

    confidence = str(payload.get("confidence_in_interpretation", "high")).lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    plan = QueryPlan(
        intent=intent,
        boards=_boards_for(intent, payload.get("boards")),
        filters=_coerce_filters(payload.get("filters")),
        group_by=None,
        assumptions=assumptions,
        confidence_in_interpretation=confidence,  # type: ignore[arg-type]
    )
    return PlanOutcome(plan)


def _history_block(history: list[ChatTurn]) -> str:
    if not history:
        return ""
    recent = history[-4:]
    lines = [f"{t.role}: {t.content[:300]}" for t in recent]
    return "Recent conversation for context only:\n" + "\n".join(lines) + "\n\n"


async def build_plan(
    question: str, history: list[ChatTurn], provider: LLMProvider | None
) -> PlanOutcome:
    if provider is None:
        plan = fallback.keyword_plan(question)
        return PlanOutcome(
            plan, degraded=True,
            degraded_reason="No LLM provider is configured; using keyword routing.",
        )

    user = f"{_history_block(history)}Question: {question}"
    try:
        payload = await provider.complete_json(
            PLANNER_SYSTEM, user, schema_hint=PLANNER_SCHEMA_HINT, max_tokens=800
        )
    except LLMError as exc:
        logger.warning("planner LLM failed, falling back to keywords: %s", exc)
        plan = fallback.keyword_plan(question)
        return PlanOutcome(
            plan, degraded=True,
            degraded_reason=f"The language model was unavailable ({exc}); "
                            "the question was routed by keyword instead.",
        )

    return parse_plan(payload, question)
