"""Deterministic work order / delivery metrics.

Note what is deliberately absent: there are no collections or AR-ageing metrics.
Four columns in the source (Collection status, Collection Date, Expected Billing
Month, Actual Collection Month) are 100% empty, so those metrics cannot be
computed honestly. Shipping them would mean shipping nulls dressed as analysis.
"""
from __future__ import annotations

import pandas as pd

from ..data.quality import build_metric, format_inr, sum_with_provenance
from ..models.schemas import Breakdown, BreakdownRow, MetricResult


def total_work_orders(df: pd.DataFrame) -> MetricResult:
    return build_metric(
        "total_work_orders", "Total work orders", len(df), "count",
        formula="count of work order records",
        definition="Every work order on the board, in any state.",
        rows_considered=len(df), rows_included=len(df),
    )


def active_work_orders(df: pd.DataFrame) -> MetricResult:
    active = df[df["is_active"] == True] if not df.empty else df  # noqa: E712
    return build_metric(
        "active_work_orders", "Active work orders", len(active), "count",
        formula="count where execution status is Not Started, Ongoing or Partially Complete",
        definition="Work that is committed but not yet finished.",
        # Every row was examined and classified -- nothing was excluded. A count
        # of a subset is the answer, not a sample of it.
        rows_considered=len(df), rows_included=len(df),
    )


def completed_work_orders(df: pd.DataFrame) -> MetricResult:
    done = df[df["is_complete"] == True] if not df.empty else df  # noqa: E712
    return build_metric(
        "completed_work_orders", "Completed work orders", len(done), "count",
        formula="count where execution status = Completed",
        definition=(
            "Includes recurring contracts marked 'Executed until current month', "
            "which are delivering on schedule."
        ),
        rows_considered=len(df), rows_included=len(df),
    )


def delayed_work_orders(df: pd.DataFrame) -> MetricResult:
    """Work orders past their planned end date and not complete.

    Rows with no planned end date are EXCLUDED, not assumed on-time. Claiming
    a work order is not delayed when we simply cannot tell would be a fabrication.
    """
    if df.empty:
        return build_metric("delayed_work_orders", "Delayed work orders", 0, "count",
                            rows_considered=0, rows_included=0)
    delayed = df[df["is_delayed"] == True]  # noqa: E712
    undeterminable = int(
        df.apply(
            lambda r: (not r["is_complete"]) and pd.isna(r["end_date"]), axis=1
        ).sum()
    )
    return build_metric(
        "delayed_work_orders", "Delayed work orders", len(delayed), "count",
        formula="count where planned end date < today and status is not Completed",
        definition="Live work that has passed its planned end date.",
        rows_considered=len(df), rows_included=len(df) - undeterminable,
        exclusion_reasons={"no planned end date, so delay cannot be determined": undeterminable},
        note=(
            f"{undeterminable} incomplete work orders have no planned end date and "
            "could not be assessed for delay." if undeterminable else None
        ),
    )


def completion_rate(df: pd.DataFrame) -> MetricResult:
    if df.empty:
        return build_metric(
            "completion_rate", "Completion rate", None, "percent",
            rows_considered=0, rows_included=0,
            exclusion_reasons={"no work orders": 0},
            note="No work orders available.",
        )
    known = df[df["exec_status_norm"] != "Unknown"]
    if known.empty:
        return build_metric(
            "completion_rate", "Completion rate", None, "percent",
            rows_considered=len(df), rows_included=0,
            exclusion_reasons={"execution status is blank or unrecognised": len(df)},
            note="No work order has a recognisable execution status.",
        )
    done = int((known["is_complete"] == True).sum())  # noqa: E712
    return build_metric(
        "completion_rate", "Completion rate", done / len(known) * 100, "percent",
        formula=f"{done} completed / {len(known)} work orders with a known status",
        definition="Share of work orders that are delivered.",
        rows_considered=len(df), rows_included=len(known),
        exclusion_reasons={"execution status is blank or unrecognised": len(df) - len(known)},
    )


def average_project_duration(df: pd.DataFrame) -> MetricResult:
    durations = (
        pd.to_numeric(df["duration_days"], errors="coerce").dropna()
        if not df.empty else pd.Series(dtype=float)
    )
    if durations.empty:
        return build_metric(
            "average_project_duration", "Average project duration", None, "days",
            rows_considered=len(df), rows_included=0,
            exclusion_reasons={"needs both a start date and a delivery date": len(df)},
        )
    return build_metric(
        "average_project_duration", "Average project duration",
        float(durations.median()), "days",
        formula="median of (delivery date - planned start date)",
        definition=(
            "Median rather than mean, because a handful of long-running contracts "
            "would otherwise dominate. Only projects with both dates are counted."
        ),
        rows_considered=len(df), rows_included=int(len(durations)),
        exclusion_reasons={
            "missing a start or delivery date": len(df) - len(durations)
        },
    )


def overdue_backlog_value(df: pd.DataFrame) -> MetricResult:
    delayed = df[df["is_delayed"] == True] if not df.empty else df  # noqa: E712
    total, considered, included, reasons = sum_with_provenance(
        delayed, "amount_excl_gst", scope_label="delayed work orders",
        total_universe=len(df),
    )
    return build_metric(
        "overdue_backlog_value", "Value in delayed work", total, "inr",
        formula="sum of work order value (excl GST) where the work order is delayed",
        definition="Contracted value tied up in work that has slipped its end date.",
        rows_considered=considered, rows_included=included, exclusion_reasons=reasons,
    )


def billing_gap(df: pd.DataFrame) -> MetricResult:
    """Contracted value not yet billed, across work orders where both figures exist."""
    if df.empty:
        return build_metric("billing_gap", "Unbilled contracted value", None, "inr",
                            rows_considered=0, rows_included=0)
    working = df.copy()
    working["_amt"] = pd.to_numeric(working["amount_excl_gst"], errors="coerce")
    working["_billed"] = pd.to_numeric(working["billed_value"], errors="coerce").fillna(0.0)
    usable = working.dropna(subset=["_amt"])
    if usable.empty:
        return build_metric(
            "billing_gap", "Unbilled contracted value", None, "inr",
            rows_considered=len(df), rows_included=0,
            exclusion_reasons={"work order value is blank": len(df)},
        )
    gap = (usable["_amt"] - usable["_billed"]).clip(lower=0).sum()
    unbilled_rows = int((usable["_amt"] - usable["_billed"] > 0).sum())
    return build_metric(
        "billing_gap", "Unbilled contracted value", float(gap), "inr",
        formula="sum of max(work order value - billed value, 0)",
        definition=(
            "Contracted value not yet invoiced. Work orders with no billed value "
            "recorded are treated as unbilled."
        ),
        rows_considered=len(df), rows_included=int(len(usable)),
        exclusion_reasons={"work order value is blank": len(df) - len(usable)},
        note=f"{unbilled_rows} work orders have value still to bill.",
    )


def unbilled_completed(df: pd.DataFrame) -> MetricResult:
    """Completed work that has not been invoiced -- money already earned.

    This is the highest-signal operational risk metric available from this board.
    """
    if df.empty:
        return build_metric("unbilled_completed", "Completed but not billed", 0, "count",
                            rows_considered=0, rows_included=0)
    done = df[df["is_complete"] == True]  # noqa: E712
    if done.empty:
        return build_metric("unbilled_completed", "Completed but not billed", 0, "count",
                            rows_considered=len(df), rows_included=0)
    status = done["invoice_status"].fillna("").str.lower()
    unbilled = done[status.str.contains("not billed") | (status == "")]
    value = pd.to_numeric(unbilled["amount_excl_gst"], errors="coerce").dropna().sum()
    return build_metric(
        "unbilled_completed", "Completed but not billed", len(unbilled), "count",
        formula="count where execution status = Completed and invoice status is 'Not billed yet' or blank",
        definition=(
            "Delivered work with no invoice recorded. Revenue already earned but "
            "not yet claimed."
        ),
        rows_considered=len(done), rows_included=len(done),
        note=f"Approximately {format_inr(float(value))} of delivered work value." if value else None,
    )


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------

def _wo_breakdown(df: pd.DataFrame, column: str, key: str, title: str,
                  dimension: str, chart: str = "bar") -> Breakdown:
    if df.empty or column not in df.columns:
        return Breakdown(key=key, title=title, dimension=dimension,
                         columns=["work_orders", "completed", "delayed"], rows=[],
                         chart=chart,  # type: ignore[arg-type]
                         note="No work orders available for this breakdown.")
    working = df.copy()
    working[column] = working[column].fillna("Not specified")
    grouped = working.groupby(column, dropna=False).agg(
        work_orders=("wo_id", "size"),
        completed=("is_complete", "sum"),
        delayed=("is_delayed", "sum"),
        value=("amount_excl_gst", "sum"),
    ).reset_index().sort_values("work_orders", ascending=False)

    rows = [
        BreakdownRow(
            key=str(r[column]), label=str(r[column]),
            values={
                "work_orders": int(r["work_orders"]),
                "completed": int(r["completed"]),
                "delayed": int(r["delayed"]),
                "completion_rate": (
                    float(r["completed"]) / int(r["work_orders"]) * 100
                    if r["work_orders"] else None
                ),
                "value": float(r["value"]) if pd.notna(r["value"]) else None,
            },
            display={
                "work_orders": f"{int(r['work_orders']):,}",
                "completed": f"{int(r['completed']):,}",
                "delayed": f"{int(r['delayed']):,}",
                "completion_rate": (
                    f"{float(r['completed']) / int(r['work_orders']) * 100:.0f}%"
                    if r["work_orders"] else "-"
                ),
                "value": format_inr(float(r["value"]) if pd.notna(r["value"]) else None),
            },
        )
        for _, r in grouped.iterrows()
    ]
    return Breakdown(key=key, title=title, dimension=dimension,
                     columns=["work_orders", "completed", "delayed", "completion_rate", "value"],
                     rows=rows, chart=chart)  # type: ignore[arg-type]


def work_orders_by_sector(df: pd.DataFrame) -> Breakdown:
    return _wo_breakdown(df, "sector_norm", "wo_by_sector",
                         "Work orders by sector", "sector")


def work_orders_by_status(df: pd.DataFrame) -> Breakdown:
    return _wo_breakdown(df, "exec_status_norm", "wo_by_status",
                         "Work orders by execution status", "status")


def work_orders_by_customer(df: pd.DataFrame) -> Breakdown:
    bd = _wo_breakdown(df, "customer_code", "wo_by_customer",
                       "Work orders by customer", "customer", chart="table")
    bd.rows = bd.rows[:10]
    return bd


def delayed_work_detail(df: pd.DataFrame, limit: int = 10) -> Breakdown:
    if df.empty:
        return Breakdown(key="delayed_detail", title="Delayed work orders",
                         dimension="work_order", columns=["delay_days", "sector", "value"],
                         rows=[], chart="table")
    delayed = df[df["is_delayed"] == True].copy()  # noqa: E712
    delayed["_delay"] = pd.to_numeric(delayed["delay_days"], errors="coerce")
    delayed = delayed.nlargest(limit, "_delay")
    rows = [
        BreakdownRow(
            key=str(r["wo_id"] or r["deal_name_raw"] or "-"),
            label=f"{r['deal_name_raw'] or 'Unnamed'} ({r['wo_id'] or '-'})",
            values={
                "delay_days": float(r["_delay"]) if pd.notna(r["_delay"]) else None,
                "value": float(r["amount_excl_gst"]) if pd.notna(r["amount_excl_gst"]) else None,
            },
            display={
                "delay_days": f"{int(r['_delay'])} days" if pd.notna(r["_delay"]) else "-",
                "sector": str(r["sector_norm"] or "-"),
                "value": format_inr(
                    float(r["amount_excl_gst"]) if pd.notna(r["amount_excl_gst"]) else None
                ),
                "status": str(r["exec_status_norm"] or "-"),
            },
        )
        for _, r in delayed.iterrows()
    ]
    return Breakdown(key="delayed_detail", title="Most delayed work orders",
                     dimension="work_order",
                     columns=["delay_days", "sector", "status", "value"],
                     rows=rows, chart="table")
