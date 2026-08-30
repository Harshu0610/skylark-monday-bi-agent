"""Intent -> analysis dispatch.

Each handler is plain Python: it takes the canonical frames plus a QueryPlan and
returns an AnalysisResult. No LLM is involved below this line, which is what
makes every number reproducible and testable.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..config import get_settings
from ..data.quality import build_ledger, format_inr
from ..models.schemas import (
    AnalysisResult,
    Breakdown,
    Filters,
    Intent,
    MetricResult,
    QueryPlan,
)
from . import cross_board as cb
from . import deals as dm
from . import work_orders as wm

# ---------------------------------------------------------------------------
# Date windows
# ---------------------------------------------------------------------------

def fiscal_quarter_bounds(today: date, offset: int = 0) -> tuple[date, date, str]:
    """Quarter bounds using the configured fiscal year start month.

    Indian companies typically run April-March, so "this quarter" is stated as
    an explicit assumption rather than silently assumed to be calendar.
    """
    start_month = get_settings().fiscal_year_start_month
    months_since = (today.month - start_month) % 12
    q_index = months_since // 3 + offset

    year = today.year
    month = start_month + q_index * 3
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1

    start = date(year, month, 1)
    end_month, end_year = month + 3, year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end = date(end_year, end_month, 1) - timedelta(days=1)

    fy_year = year if month >= start_month else year - 1
    label = f"Q{(q_index % 4) + 1} FY{str(fy_year + 1)[-2:]}" if start_month != 1 else \
            f"Q{(q_index % 4) + 1} {year}"
    return start, end, label


def resolve_date_range(filters: Filters, today: date) -> tuple[date, date, str] | None:
    dr = filters.date_range
    if dr is None:
        return None
    if dr.start and dr.end:
        return dr.start, dr.end, f"{dr.start.isoformat()} to {dr.end.isoformat()}"
    preset = dr.preset.value if dr.preset else None
    if preset in (None, "all_time"):
        return None
    if preset == "this_quarter":
        return fiscal_quarter_bounds(today, 0)
    if preset == "last_quarter":
        return fiscal_quarter_bounds(today, -1)
    if preset == "this_month":
        start = today.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1), "this month"
    if preset == "this_year":
        return date(today.year, 1, 1), date(today.year, 12, 31), f"{today.year}"
    if preset == "next_90_days":
        return today, today + timedelta(days=90), "the next 90 days"
    return None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _match(series: pd.Series, needle: str) -> pd.Series:
    return series.fillna("").astype(str).str.lower().str.contains(needle.lower(), regex=False)


def apply_filters(
    df: pd.DataFrame, filters: Filters, *, board: str
) -> tuple[pd.DataFrame, list[str]]:
    """Apply plan filters. Returns the frame plus notes about filters that
    matched nothing -- silently returning an empty result is a failure mode."""
    notes: list[str] = []
    if df.empty:
        return df, notes

    out = df
    if filters.sector:
        matched = out[_match(out["sector_norm"], filters.sector)]
        if matched.empty:
            available = sorted({s for s in df["sector_norm"].dropna().unique()})
            notes.append(
                f"No {board} records found in sector '{filters.sector}'. "
                f"Sectors present: {', '.join(available) if available else 'none'}."
            )
        out = matched

    if filters.owner and not out.empty:
        matched = out[_match(out["owner_code"], filters.owner)]
        if matched.empty:
            notes.append(f"No {board} records found for owner '{filters.owner}'.")
        out = matched

    if filters.account and not out.empty:
        matched = out[_match(out["deal_name_raw"], filters.account)]
        if matched.empty:
            notes.append(f"No {board} records found for account '{filters.account}'.")
        out = matched

    if filters.nature_of_work and not out.empty and "nature_of_work" in out.columns:
        out = out[_match(out["nature_of_work"], filters.nature_of_work)]

    if filters.status and not out.empty:
        wanted = {s.lower() for s in filters.status}
        col = "status_norm" if "status_norm" in out.columns else "exec_status_norm"
        out = out[out[col].fillna("").str.lower().isin(wanted)]

    if filters.stage and not out.empty and "stage_norm" in out.columns:
        wanted = {s.lower() for s in filters.stage}
        out = out[out["stage_norm"].fillna("").str.lower().isin(wanted)]

    return out, notes


# ---------------------------------------------------------------------------
# Field sets used for per-query confidence scoring
# ---------------------------------------------------------------------------

FIELDS_FOR_INTENT: dict[Intent, list[str]] = {
    Intent.PIPELINE: ["amount_value", "status_norm"],
    Intent.WEIGHTED_PIPELINE: ["amount_value", "status_norm", "probability_weight"],
    Intent.WON_REVENUE: ["amount_value", "status_norm"],
    Intent.WIN_RATE: ["status_norm"],
    Intent.DEAL_RISK: ["amount_value", "tentative_close_date", "status_norm"],
    Intent.SECTOR_BREAKDOWN: ["amount_value", "sector_norm"],
    Intent.OWNER_PERFORMANCE: ["amount_value", "owner_code"],
    Intent.FUNNEL: ["stage_norm", "amount_value"],
    Intent.WORK_ORDER_STATUS: ["exec_status_norm"],
    Intent.DELIVERY_PERFORMANCE: ["exec_status_norm", "end_date"],
    Intent.DELAYED_WORK: ["exec_status_norm", "end_date"],
    Intent.BILLING_RISK: ["amount_excl_gst", "billed_value", "invoice_status"],
    Intent.CROSS_BOARD_SECTOR: ["sector_norm", "amount_value"],
    Intent.CROSS_BOARD_ACCOUNT: ["deal_name_norm", "amount_value"],
    Intent.EXECUTIVE_SUMMARY: ["amount_value", "status_norm", "sector_norm"],
    Intent.DATA_QUALITY: [],
    Intent.LEADERSHIP_UPDATE: ["amount_value", "status_norm", "sector_norm"],
}

DEALS_INTENTS = {
    Intent.PIPELINE, Intent.WEIGHTED_PIPELINE, Intent.WON_REVENUE, Intent.WIN_RATE,
    Intent.DEAL_RISK, Intent.SECTOR_BREAKDOWN, Intent.OWNER_PERFORMANCE, Intent.FUNNEL,
}
WORK_ORDER_INTENTS = {
    Intent.WORK_ORDER_STATUS, Intent.DELIVERY_PERFORMANCE, Intent.DELAYED_WORK,
    Intent.BILLING_RISK,
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _scope_for(intent: Intent, deals: pd.DataFrame, work_orders: pd.DataFrame) -> pd.DataFrame:
    """The rows an answer actually rests on.

    Confidence is a statement about DATA QUALITY, not about how narrow the
    question was. A pipeline question is scored on open deals only; scoring it
    on won and lost deals too would punish it for missing values it never used.
    """
    if intent in (Intent.PIPELINE, Intent.WEIGHTED_PIPELINE, Intent.DEAL_RISK,
                  Intent.SECTOR_BREAKDOWN, Intent.OWNER_PERFORMANCE, Intent.FUNNEL):
        return deals[deals["is_open"] == True] if not deals.empty else deals  # noqa: E712
    if intent == Intent.WON_REVENUE:
        return deals[deals["is_won"] == True] if not deals.empty else deals  # noqa: E712
    if intent == Intent.WIN_RATE:
        return deals[deals["is_closed"] == True] if not deals.empty else deals  # noqa: E712
    if intent in WORK_ORDER_INTENTS:
        return work_orders
    # Cross-board and executive views are driven by live pipeline plus delivery,
    # so they are scored on open deals rather than the whole deal history.
    if not deals.empty:
        return deals[deals["is_open"] == True]  # noqa: E712
    return work_orders


def _result(
    plan: QueryPlan,
    metrics: list[MetricResult],
    breakdowns: list[Breakdown],
    scoped: pd.DataFrame,
    reports: list[dict],
    *,
    facts: list[str] | None = None,
    caveats: list[str] | None = None,
    headline: str | None = None,
    extra_notes: list[str] | None = None,
) -> AnalysisResult:
    ledger = build_ledger(
        metrics,
        scoped_frame=scoped,
        scoped_fields=FIELDS_FOR_INTENT.get(plan.intent, []),
        normalization_reports=reports,
        extra_notes=extra_notes,
    )
    return AnalysisResult(
        intent=plan.intent, headline=headline, metrics=metrics, breakdowns=breakdowns,
        ledger=ledger, facts=facts or [], caveats=caveats or [],
    )


def run_analysis(
    plan: QueryPlan,
    deals: pd.DataFrame,
    work_orders: pd.DataFrame,
    reports: list[dict],
    today: date | None = None,
) -> AnalysisResult:
    today = today or date.today()
    d, d_notes = apply_filters(deals, plan.filters, board="deal")
    w, w_notes = apply_filters(work_orders, plan.filters, board="work order")
    notes = d_notes + w_notes
    window = resolve_date_range(plan.filters, today)
    intent = plan.intent

    metrics: list[MetricResult] = []
    breakdowns: list[Breakdown] = []
    caveats: list[str] = list(notes)

    # -- Sales ------------------------------------------------------------
    if intent in (Intent.PIPELINE, Intent.WEIGHTED_PIPELINE):
        metrics = [
            dm.total_open_pipeline(d),
            dm.weighted_pipeline(d),
            dm.open_deal_count(d),
            dm.median_deal_size(d),
        ]
        if window:
            start, end, label = window
            metrics.insert(1, dm.deals_closing_in_range(d, start, end, label))
        breakdowns = [dm.pipeline_by_sector(d), dm.top_deals(d)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.WON_REVENUE:
        metrics = [dm.won_revenue(d), dm.win_rate(d), dm.lost_value(d)]
        breakdowns = [dm.pipeline_by_sector(d)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.WIN_RATE:
        metrics = [dm.win_rate(d), dm.won_revenue(d), dm.lost_value(d)]
        return _result(plan, metrics, [], _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.SECTOR_BREAKDOWN:
        metrics = [dm.total_open_pipeline(d), dm.open_deal_count(d)]
        breakdowns = [dm.pipeline_by_sector(d)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.OWNER_PERFORMANCE:
        metrics = [dm.total_open_pipeline(d), dm.win_rate(d)]
        breakdowns = [dm.pipeline_by_owner(d)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.FUNNEL:
        metrics = [dm.open_deal_count(d), dm.total_open_pipeline(d)]
        breakdowns = [dm.pipeline_by_stage(d)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.DEAL_RISK:
        metrics = [
            dm.stale_deals(d), dm.stale_deal_value(d),
            dm.pipeline_concentration(d), dm.average_pipeline_age(d),
        ]
        breakdowns = [dm.top_deals(d)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    # -- Operations -------------------------------------------------------
    if intent in (Intent.WORK_ORDER_STATUS, Intent.DELIVERY_PERFORMANCE):
        metrics = [
            wm.total_work_orders(w), wm.active_work_orders(w),
            wm.completed_work_orders(w), wm.completion_rate(w),
            wm.delayed_work_orders(w), wm.average_project_duration(w),
        ]
        breakdowns = [wm.work_orders_by_status(w), wm.work_orders_by_sector(w)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.DELAYED_WORK:
        metrics = [
            wm.delayed_work_orders(w), wm.overdue_backlog_value(w),
            wm.active_work_orders(w), wm.completion_rate(w),
        ]
        breakdowns = [wm.delayed_work_detail(w), wm.work_orders_by_sector(w)]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    if intent == Intent.BILLING_RISK:
        metrics = [
            wm.billing_gap(w), wm.unbilled_completed(w),
            wm.completed_work_orders(w), wm.total_work_orders(w),
        ]
        breakdowns = [wm.work_orders_by_sector(w)]
        caveats.append(
            "Collection and receivables ageing cannot be analysed: the collection "
            "status and collection date columns are empty for every work order."
        )
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    # -- Cross-board ------------------------------------------------------
    if intent == Intent.CROSS_BOARD_SECTOR:
        metrics = [
            dm.total_open_pipeline(d), wm.completion_rate(w),
            wm.delayed_work_orders(w), cb.account_link_coverage(d, w),
        ]
        breakdowns = [
            cb.sector_opportunity_matrix(d, w),
            cb.won_vs_delivered_by_sector(d, w),
        ]
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports,
                       caveats=caveats)

    if intent == Intent.CROSS_BOARD_ACCOUNT:
        metrics = [
            cb.account_link_coverage(d, w), dm.total_open_pipeline(d),
            wm.delayed_work_orders(w),
        ]
        breakdowns = [cb.accounts_at_risk(d, w), cb.owner_sales_vs_delivery(d, w)]
        caveats.append(cb.customer_join_unavailable_note())
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports,
                       caveats=caveats)

    # -- Executive --------------------------------------------------------
    if intent in (Intent.EXECUTIVE_SUMMARY, Intent.LEADERSHIP_UPDATE):
        metrics = [
            dm.total_open_pipeline(d), dm.weighted_pipeline(d), dm.won_revenue(d),
            dm.win_rate(d), wm.active_work_orders(w), wm.completion_rate(w),
            wm.delayed_work_orders(w), dm.stale_deal_value(d),
            dm.pipeline_concentration(d), wm.unbilled_completed(w),
        ]
        breakdowns = [
            dm.pipeline_by_sector(d),
            cb.sector_opportunity_matrix(d, w),
            cb.accounts_at_risk(d, w),
        ]
        if window:
            start, end, label = window
            metrics.insert(2, dm.deals_closing_in_range(d, start, end, label))
        return _result(plan, metrics, breakdowns, _scope_for(intent, d, w), reports, caveats=caveats)

    # -- Data quality -----------------------------------------------------
    if intent == Intent.DATA_QUALITY:
        return data_quality_report(plan, d, w, reports)

    return AnalysisResult(
        intent=intent,
        unsupported=(
            "I don't have an analysis for that question yet. I can answer questions "
            "about pipeline, won revenue, win rate, deal risk, sector and owner "
            "breakdowns, work order status and delays, billing gaps, cross-board "
            "sector and account comparisons, executive summaries, and data quality."
        ),
    )


def data_quality_report(
    plan: QueryPlan, deals: pd.DataFrame, work_orders: pd.DataFrame, reports: list[dict]
) -> AnalysisResult:
    """A first-class answer, not an error page.

    The messiness in this dataset is deliberate, so being able to describe it
    precisely is a capability rather than an apology.
    """
    from ..data.quality import build_metric, collect_flags, describe_flag

    metrics: list[MetricResult] = []

    if not deals.empty:
        missing_amt = int(deals["amount_value"].isna().sum())
        won = deals[deals["is_won"] == True]  # noqa: E712
        won_missing = int(won["amount_value"].isna().sum()) if not won.empty else 0
        metrics.append(build_metric(
            "deals_missing_value", "Deals with no value recorded",
            missing_amt / len(deals) * 100, "percent",
            formula=f"{missing_amt} of {len(deals)} deals",
            definition="Deals where the value field is blank in Monday.com.",
            rows_considered=len(deals), rows_included=len(deals) - missing_amt,
        ))
        if not won.empty:
            metrics.append(build_metric(
                "won_missing_value", "Won deals with no value recorded",
                won_missing / len(won) * 100, "percent",
                formula=f"{won_missing} of {len(won)} won deals",
                definition=(
                    "The most consequential gap in this dataset: won revenue is "
                    "materially understated because most won deals carry no value."
                ),
                rows_considered=len(won), rows_included=len(won) - won_missing,
            ))
        missing_close = int(deals["tentative_close_date"].isna().sum())
        metrics.append(build_metric(
            "deals_missing_close_date", "Deals with no expected close date",
            missing_close / len(deals) * 100, "percent",
            formula=f"{missing_close} of {len(deals)} deals",
            definition="Deals that cannot be placed in a forecast period.",
            rows_considered=len(deals), rows_included=len(deals) - missing_close,
        ))

    if not work_orders.empty:
        no_end = int(work_orders["end_date"].isna().sum())
        metrics.append(build_metric(
            "wo_missing_end_date", "Work orders with no planned end date",
            no_end / len(work_orders) * 100, "percent",
            formula=f"{no_end} of {len(work_orders)} work orders",
            definition="Work orders whose delay status cannot be determined.",
            rows_considered=len(work_orders), rows_included=len(work_orders) - no_end,
        ))
        no_billed = int(work_orders["billed_value"].isna().sum())
        metrics.append(build_metric(
            "wo_missing_billed", "Work orders with no billed value",
            no_billed / len(work_orders) * 100, "percent",
            formula=f"{no_billed} of {len(work_orders)} work orders",
            definition="Work orders where billing progress is not recorded.",
            rows_considered=len(work_orders), rows_included=len(work_orders) - no_billed,
        ))

    rows: list = []
    from ..models.schemas import BreakdownRow
    for df, label in ((deals, "Deals"), (work_orders, "Work Orders")):
        for flag, count in sorted(collect_flags(df).items(), key=lambda kv: -kv[1])[:8]:
            rows.append(BreakdownRow(
                key=f"{label}:{flag}", label=f"{label}: {describe_flag(flag)}",
                values={"records": count},
                display={"records": f"{count:,}"},
            ))

    breakdown = Breakdown(
        key="quality_issues", title="Data quality issues by type", dimension="issue",
        columns=["records"], rows=rows, chart="table",
        note="Counts are records affected, not records discarded. Nothing is dropped silently.",
    )

    caveats = [
        "Collection status, collection date, expected billing month and actual "
        "collection month are empty for every work order, so receivables analysis "
        "is not possible.",
        "Customer codes cannot be matched across boards: Deals uses COMPANY### and "
        "Work Orders uses WOCOMPANY_###, with no overlap.",
    ]

    return _result(
        plan, metrics, [breakdown], deals, reports, caveats=caveats,
        extra_notes=["This is a report about the data itself, so no records were excluded."],
    )
