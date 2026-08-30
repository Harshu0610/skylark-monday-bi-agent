"""Dashboard overview: the at-a-glance state of the business.

Everything here is computed from the same canonical frames as the chat answers,
so the landing page and the conversation can never disagree.

ON TRENDS AND DELTAS
    A dashboard wants a sparkline and a "+12% vs last period" chip on every
    card. We only ship those where the underlying data can actually support one.

    Monday.com gives us the CURRENT state of each board, not a history of it.
    There are no snapshots, so "open pipeline vs 30 days ago" is unknowable --
    we do not know what the pipeline looked like 30 days ago. Any number in that
    slot would be invented.

    What IS knowable is anything with a date column on the record itself:
    pipeline CREATED per month (created_date), deals WON per month (close date),
    and work orders FALLING DUE per month (end date). Those are real series, so
    those are the ones that get trends. Cards without a defensible series show a
    factual sub-line instead of a decorative arrow.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..data.quality import format_inr
from . import cross_board as cb
from . import deals as dm
from . import work_orders as wm

# How many months of history to build a sparkline from.
SERIES_MONTHS = 12


def _month_starts(today: date, months: int) -> list[date]:
    out: list[date] = []
    year, month = today.year, today.month
    for _ in range(months):
        out.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(out))


def _month_of(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    return None


def _series(
    df: pd.DataFrame, date_column: str, months: list[date],
    *, value_column: str | None = None,
) -> list[float]:
    """Monthly totals (or counts) bucketed by a date column on the record."""
    buckets = {m: 0.0 for m in months}
    if df.empty or date_column not in df.columns:
        return [0.0] * len(months)

    for _, row in df.iterrows():
        bucket = _month_of(row.get(date_column))
        if bucket is None or bucket not in buckets:
            continue
        if value_column is None:
            buckets[bucket] += 1.0
        else:
            amount = pd.to_numeric(pd.Series([row.get(value_column)]), errors="coerce").iloc[0]
            if pd.notna(amount):
                buckets[bucket] += float(amount)
    return [buckets[m] for m in months]


def _trend(series: list[float]) -> dict[str, Any] | None:
    """Change between the two most recent months that contain activity.

    Comparing against a zero month produces an infinite or meaningless
    percentage, so we compare the last two POPULATED months and say which they
    were. If fewer than two exist, there is no trend to report.
    """
    populated = [(i, v) for i, v in enumerate(series) if v > 0]
    if len(populated) < 2:
        return None
    (_, prev), (_, curr) = populated[-2], populated[-1]
    if prev == 0:
        return None
    return {
        "direction": "up" if curr >= prev else "down",
        "percent": abs((curr - prev) / prev * 100),
        "basis": "vs the previous month with activity",
    }


def _card(
    key: str, label: str, display: str, *,
    tone: str = "neutral",
    sub: str | None = None,
    series: list[float] | None = None,
    trend: dict | None = None,
    note: str | None = None,
    metric: MetricResult | None = None,
) -> dict[str, Any]:
    return {
        "key": key, "label": label, "display": display, "tone": tone,
        "sub": sub, "series": series or [], "trend": trend, "note": note,
        "provenance": metric.model_dump() if metric else None,
    }


def build_overview(
    deals: pd.DataFrame, work_orders: pd.DataFrame, today: date | None = None
) -> dict[str, Any]:
    today = today or date.today()
    months = _month_starts(today, SERIES_MONTHS)
    month_labels = [m.strftime("%b %y") for m in months]

    pipeline = dm.total_open_pipeline(deals)
    weighted = dm.weighted_pipeline(deals)
    won = dm.won_revenue(deals)
    delayed = wm.delayed_work_orders(work_orders)
    backlog = wm.overdue_backlog_value(work_orders)
    completion = wm.completion_rate(work_orders)
    active = wm.active_work_orders(work_orders)
    open_count = dm.open_deal_count(deals)
    win = dm.win_rate(deals)
    unbilled = wm.unbilled_completed(work_orders)

    # --- series that the data genuinely supports -------------------------
    created_series = _series(deals, "created_date", months, value_column="amount_value")

    won_deals = deals[deals["is_won"] == True] if not deals.empty else deals  # noqa: E712
    if not won_deals.empty:
        closed = won_deals.copy()
        closed["_close"] = closed.apply(
            lambda r: r["actual_close_date"] or r["tentative_close_date"], axis=1
        )
        won_series = _series(closed, "_close", months, value_column="amount_value")
    else:
        won_series = [0.0] * len(months)

    delayed_only = (
        work_orders[work_orders["is_delayed"] == True]  # noqa: E712
        if not work_orders.empty else work_orders
    )
    delayed_series = _series(delayed_only, "end_date", months)

    # --- pulse cards ------------------------------------------------------
    cards = [
        _card(
            "open_pipeline", "Open pipeline", pipeline.display, tone="accent",
            sub=f"{pipeline.rows_included} of {pipeline.rows_considered} open deals valued",
            note=(
                "Monday.com stores the current state of the board, not a history "
                "of it, so there is no earlier pipeline figure to compare against. "
                "The trend below is new pipeline CREATED per month, which the deal "
                "creation dates do support."
            ),
            series=created_series,
            trend=_trend(created_series),
            metric=pipeline,
        ),
        _card(
            "won_revenue", "Won revenue", won.display, tone="positive",
            sub=(
                f"{won.rows_included} of {won.rows_considered} won deals have a value"
                if won.rows_considered else "no won deals on record"
            ),
            note=won.note,
            series=won_series,
            trend=_trend(won_series),
            metric=won,
        ),
        _card(
            "delayed_work", "Work orders at risk",
            f"{int(delayed.value):,}" if delayed.value is not None else "not available",
            tone="warning",
            sub=(
                f"{backlog.display} of contracted value"
                if backlog.value else "value not recorded"
            ),
            note=delayed.note,
            series=delayed_series,
            trend=None,   # a count of overdue work has no meaningful month-on-month rate
            metric=delayed,
        ),
        _card(
            "completion_rate", "Delivery completion", completion.display,
            tone="neutral",
            sub=f"{int(active.value):,} work orders still active" if active.value is not None else None,
            note=(
                f"Based on {completion.rows_included} of {completion.rows_considered} "
                "work orders with a recognisable status."
                if completion.rows_considered else None
            ),
            metric=completion,
        ),
    ]

    # --- the one alert worth interrupting someone for ---------------------
    alert = None
    matrix = cb.sector_opportunity_matrix(deals, work_orders)
    fix = [r for r in matrix.rows if r.display.get("quadrant") == "Fix delivery"]

    if fix:
        worst = min(
            fix, key=lambda r: r.values.get("completion_rate") or 100
        )
        rate = worst.values.get("completion_rate")
        alert = {
            "tone": "warning",
            "title": (
                f"{worst.label} is selling faster than it is delivering"
            ),
            "detail": (
                f"{worst.display.get('pipeline')} of open pipeline against a "
                f"{rate:.0f}% completion rate — {worst.display.get('delayed')} of "
                f"{worst.display.get('work_orders')} work orders are delayed."
            ),
            "question": "Which sectors have the strongest pipeline but weak execution?",
            "cta": "See the cross-board analysis",
        }
    elif delayed.value:
        alert = {
            "tone": "warning",
            "title": f"{int(delayed.value)} work orders are past their planned end date",
            "detail": (
                f"{backlog.display} of contracted value is tied up in work that has "
                "slipped." if backlog.value else "Planned end dates have passed."
            ),
            "question": "How many work orders are delayed?",
            "cta": "See the delay breakdown",
        }
    elif unbilled.value:
        alert = {
            "tone": "warning",
            "title": f"{int(unbilled.value)} work orders are delivered but not invoiced",
            "detail": unbilled.note or "Revenue earned and not yet claimed.",
            "question": "How much work is delivered but unbilled?",
            "cta": "See the billing gap",
        }

    # --- headline data-quality note, surfaced rather than buried ----------
    quality = None
    if won.rows_considered and won.rows_included < won.rows_considered:
        missing = won.rows_considered - won.rows_included
        pct = missing / won.rows_considered * 100
        quality = {
            "title": f"{pct:.0f}% of won deals have no value recorded",
            "detail": (
                f"{missing} of {won.rows_considered} won deals are blank, so reported "
                "won revenue is a floor rather than a figure."
            ),
            "question": "What data quality problems do we have?",
        }

    # Operational risks summary list
    stale_metric = dm.stale_deals(deals)
    stale_val = dm.stale_deal_value(deals)
    delayed_details = wm.delayed_work_detail(work_orders, limit=5)
    top_deals_list = dm.top_deals(deals, limit=5)

    return {
        "cards": cards,
        "series_labels": month_labels,
        "alert": alert,
        "quality": quality,
        "secondary": [
            {"label": "Weighted pipeline", "display": weighted.display, "provenance": weighted.model_dump()},
            {"label": "Open deals", "display": open_count.display, "provenance": open_count.model_dump()},
            {"label": "Win rate", "display": win.display, "provenance": win.model_dump()},
            {"label": "Delivered, not invoiced", "display": unbilled.display, "provenance": unbilled.model_dump()},
            {"label": "Stale open deals", "display": stale_metric.display, "provenance": stale_metric.model_dump()},
            {"label": "Stale pipeline value", "display": stale_val.display, "provenance": stale_val.model_dump()},
        ],
        "delayed_preview": delayed_details.model_dump(),
        "top_deals_preview": top_deals_list.model_dump(),
    }


SUGGESTED_QUESTIONS = [
    {
        "category": "Pipeline", "icon": "pipeline", "tone": "accent",
        "question": "What's our total pipeline?",
        "caption": "Open opportunities, with every excluded record accounted for",
    },
    {
        "category": "Revenue", "icon": "revenue", "tone": "positive",
        "question": "What's our won revenue?",
        "caption": "Reported alongside what the data cannot tell us",
    },
    {
        "category": "Delivery", "icon": "delivery", "tone": "warning",
        "question": "How many work orders are delayed?",
        "caption": "Project execution across the work order book",
    },
    {
        "category": "Data quality", "icon": "quality", "tone": "neutral",
        "question": "What data quality problems do we have?",
        "caption": "Missing, inconsistent and stale records",
    },
    {
        "category": "Performance", "icon": "performance", "tone": "violet",
        "question": "Which sectors have the strongest pipeline but weak execution?",
        "caption": "Cross-board opportunity versus delivery",
    },
    {
        "category": "Leadership", "icon": "leadership", "tone": "pink",
        "question": "Prepare this week's leadership update.",
        "caption": "Risks, movement and talking points",
    },
]
