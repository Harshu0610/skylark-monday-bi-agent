"""Typed contracts shared across the pipeline.

The important one is MetricResult: every number the system produces carries its
own provenance. That is what makes the data-quality ledger possible, and it is
why the LLM never needs to be trusted with arithmetic.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Query planning
# ---------------------------------------------------------------------------

class Intent(str, Enum):
    PIPELINE = "pipeline"
    WEIGHTED_PIPELINE = "weighted_pipeline"
    WON_REVENUE = "won_revenue"
    WIN_RATE = "win_rate"
    DEAL_RISK = "deal_risk"
    SECTOR_BREAKDOWN = "sector_breakdown"
    OWNER_PERFORMANCE = "owner_performance"
    FUNNEL = "funnel"
    WORK_ORDER_STATUS = "work_order_status"
    DELIVERY_PERFORMANCE = "delivery_performance"
    DELAYED_WORK = "delayed_work"
    BILLING_RISK = "billing_risk"
    CROSS_BOARD_SECTOR = "cross_board_sector"
    CROSS_BOARD_ACCOUNT = "cross_board_account"
    EXECUTIVE_SUMMARY = "executive_summary"
    PERIOD_COMPARISON = "period_comparison"
    DATA_QUALITY = "data_quality"
    LEADERSHIP_UPDATE = "leadership_update"


class Board(str, Enum):
    DEALS = "deals"
    WORK_ORDERS = "work_orders"


class GroupBy(str, Enum):
    SECTOR = "sector"
    OWNER = "owner"
    STAGE = "stage"
    STATUS = "status"
    ACCOUNT = "account"
    MONTH = "month"


class DatePreset(str, Enum):
    THIS_QUARTER = "this_quarter"
    LAST_QUARTER = "last_quarter"
    THIS_MONTH = "this_month"
    THIS_YEAR = "this_year"
    NEXT_90_DAYS = "next_90_days"
    ALL_TIME = "all_time"


class DateRange(BaseModel):
    preset: DatePreset | None = None
    start: date | None = None
    end: date | None = None


class Filters(BaseModel):
    sector: str | None = None
    owner: str | None = None
    account: str | None = None
    status: list[str] = Field(default_factory=list)
    stage: list[str] = Field(default_factory=list)
    nature_of_work: str | None = None
    date_field: str | None = None
    date_range: DateRange | None = None


class QueryPlan(BaseModel):
    intent: Intent
    boards: list[Board]
    filters: Filters = Field(default_factory=Filters)
    metrics: list[str] = Field(default_factory=list)
    group_by: GroupBy | None = None
    assumptions: list[str] = Field(default_factory=list)
    confidence_in_interpretation: Literal["high", "medium", "low"] = "high"


# ---------------------------------------------------------------------------
# Analytics results
# ---------------------------------------------------------------------------

class MetricResult(BaseModel):
    """A single computed number, with everything needed to defend it."""

    key: str
    label: str
    value: float | int | None
    display: str
    unit: Literal["inr", "count", "percent", "days", "ratio", "none"] = "none"
    formula: str = ""
    definition: str = ""
    rows_considered: int = 0
    rows_included: int = 0
    rows_excluded: int = 0
    exclusion_reasons: dict[str, int] = Field(default_factory=dict)
    note: str | None = None


class BreakdownRow(BaseModel):
    key: str
    label: str
    values: dict[str, float | int | None]
    display: dict[str, str] = Field(default_factory=dict)


class Breakdown(BaseModel):
    key: str
    title: str
    dimension: str
    columns: list[str]
    rows: list[BreakdownRow]
    chart: Literal["bar", "funnel", "scatter", "table"] = "table"
    note: str | None = None


class QualityLedger(BaseModel):
    rows_considered: int = 0
    rows_included: int = 0
    rows_excluded: int = 0
    exclusions: dict[str, int] = Field(default_factory=dict)
    normalizations: dict[str, int] = Field(default_factory=dict)
    confidence: Literal["high", "medium", "low"] = "high"
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Everything the executor produced. Handed to the narrator as read-only."""

    intent: Intent
    headline: str | None = None
    metrics: list[MetricResult] = Field(default_factory=list)
    breakdowns: list[Breakdown] = Field(default_factory=list)
    ledger: QualityLedger = Field(default_factory=QualityLedger)
    facts: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    unsupported: str | None = None


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)


class ChatResponse(BaseModel):
    answer: str
    insight: str | None = None
    risks: list[str] = Field(default_factory=list)
    metrics: list[MetricResult] = Field(default_factory=list)
    breakdowns: list[Breakdown] = Field(default_factory=list)
    ledger: QualityLedger = Field(default_factory=QualityLedger)
    plan: QueryPlan | None = None
    assumptions: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    clarification: str | None = None
    degraded: bool = False
    degraded_reason: str | None = None
    request_id: str = ""
    duration_ms: int = 0


class BoardStatus(BaseModel):
    name: str
    board_id: str | None = None
    item_count: int = 0
    fetched_at: str | None = None
    age_seconds: int | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    monday_configured: bool
    llm_configured: bool
    llm_provider: str
    boards: list[BoardStatus] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str = ""
