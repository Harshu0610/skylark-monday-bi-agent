"""Cross-board analysis: sales pipeline against delivery execution.

THE CRITICAL DATA FINDING BEHIND THIS MODULE
--------------------------------------------
The obvious join -- customer -- is IMPOSSIBLE. The two boards mask customers in
different namespaces (Deals: COMPANY089; Work Orders: WOCOMPANY_002) with zero
overlap. Any fuzzy match between them would be fabricating a relationship that
does not exist in the data.

What DOES join:
  1. Sector          - 6 shared values after normalization. Reliable.
  2. Deal name       - 52 of 58 work-order accounts (90%) match a deal name.
  3. Owner code      - 6 shared OWNER_xxx codes.

Deal name is not unique on the Deals board (one name can carry many deals), so
it behaves as an ACCOUNT alias rather than a deal primary key. Both sides are
therefore aggregated to one row per account BEFORE joining -- a naive row-level
merge would multiply rows and inflate every total.
"""
from __future__ import annotations

import pandas as pd

from ..data.quality import build_metric, format_inr
from ..models.schemas import Breakdown, BreakdownRow, MetricResult


def _agg_deals_by_account(deals: pd.DataFrame) -> pd.DataFrame:
    if deals.empty:
        return pd.DataFrame(columns=["deal_name_norm", "open_pipeline", "open_deals",
                                     "won_deals", "lost_deals", "account_label"])
    working = deals.copy()
    working["_amt"] = pd.to_numeric(working["amount_value"], errors="coerce")
    working["_open_amt"] = working["_amt"].where(working["is_open"] == True)  # noqa: E712
    grouped = working.groupby("deal_name_norm", dropna=True).agg(
        open_pipeline=("_open_amt", "sum"),
        open_deals=("is_open", "sum"),
        won_deals=("is_won", "sum"),
        lost_deals=("is_lost", "sum"),
        account_label=("deal_name_raw", "first"),
    ).reset_index()
    return grouped


def _agg_work_orders_by_account(work_orders: pd.DataFrame) -> pd.DataFrame:
    if work_orders.empty:
        return pd.DataFrame(columns=["deal_name_norm", "work_orders", "completed",
                                     "delayed", "wo_value"])
    grouped = work_orders.groupby("deal_name_norm", dropna=True).agg(
        work_orders=("wo_id", "size"),
        completed=("is_complete", "sum"),
        delayed=("is_delayed", "sum"),
        wo_value=("amount_excl_gst", "sum"),
    ).reset_index()
    return grouped


def account_link_coverage(deals: pd.DataFrame, work_orders: pd.DataFrame) -> MetricResult:
    """How much of the work-order book can actually be tied back to a deal.

    Reported on every cross-board answer. A join is only as trustworthy as its
    coverage, and hiding the unmatched tail is how cross-board analysis lies.
    """
    wo_accounts = set(work_orders["deal_name_norm"].dropna()) if not work_orders.empty else set()
    deal_accounts = set(deals["deal_name_norm"].dropna()) if not deals.empty else set()
    matched = wo_accounts & deal_accounts
    unmatched = wo_accounts - deal_accounts

    pct = (len(matched) / len(wo_accounts) * 100) if wo_accounts else None
    return build_metric(
        "account_link_coverage", "Cross-board account coverage", pct, "percent",
        formula="work-order accounts with a matching deal name / all work-order accounts",
        definition=(
            "Deals and Work Orders are linked on deal/account name. Customer codes "
            "cannot be used -- the two boards mask customers in different, "
            "non-overlapping namespaces."
        ),
        rows_considered=len(wo_accounts), rows_included=len(matched),
        exclusion_reasons={"work-order account has no matching deal": len(unmatched)},
        note=(
            f"{len(matched)} of {len(wo_accounts)} work-order accounts matched a deal. "
            f"{len(unmatched)} unmatched and excluded from account-level comparisons."
            if wo_accounts else "No work-order accounts available to link."
        ),
    )


def sector_opportunity_matrix(
    deals: pd.DataFrame, work_orders: pd.DataFrame
) -> Breakdown:
    """Pipeline strength against delivery health, by sector.

    This is the view that only exists because both boards are present: where is
    the commercial opportunity, and can we actually deliver it?

    Quadrants (relative to the median on each axis):
      Scale           - strong pipeline, strong delivery
      Fix delivery    - strong pipeline, weak delivery
      Underinvested   - weak pipeline, strong delivery
      Deprioritise    - weak pipeline, weak delivery
    """
    if deals.empty and work_orders.empty:
        return Breakdown(key="sector_matrix", title="Sector opportunity vs execution",
                         dimension="sector",
                         columns=["pipeline", "completion_rate", "quadrant"],
                         rows=[], chart="scatter",
                         note="No data available on either board.")

    d = deals.copy()
    d["_amt"] = pd.to_numeric(d["amount_value"], errors="coerce")
    d["_open_amt"] = d["_amt"].where(d["is_open"] == True)  # noqa: E712
    dg = d.groupby("sector_norm", dropna=True).agg(
        pipeline=("_open_amt", "sum"),
        open_deals=("is_open", "sum"),
        won_deals=("is_won", "sum"),
    ).reset_index() if not d.empty else pd.DataFrame(
        columns=["sector_norm", "pipeline", "open_deals", "won_deals"])

    w = work_orders.copy()
    wg = w.groupby("sector_norm", dropna=True).agg(
        work_orders=("wo_id", "size"),
        completed=("is_complete", "sum"),
        delayed=("is_delayed", "sum"),
    ).reset_index() if not w.empty else pd.DataFrame(
        columns=["sector_norm", "work_orders", "completed", "delayed"])

    merged = pd.merge(dg, wg, on="sector_norm", how="outer")
    merged = merged[merged["sector_norm"].notna()]
    if merged.empty:
        return Breakdown(key="sector_matrix", title="Sector opportunity vs execution",
                         dimension="sector",
                         columns=["pipeline", "completion_rate", "quadrant"],
                         rows=[], chart="scatter",
                         note="No sector could be matched across the two boards.")

    merged["work_orders"] = merged["work_orders"].fillna(0).astype(int)
    merged["completed"] = merged["completed"].fillna(0).astype(int)
    merged["delayed"] = merged["delayed"].fillna(0).astype(int)
    merged["completion_rate"] = merged.apply(
        lambda r: (r["completed"] / r["work_orders"] * 100) if r["work_orders"] else None,
        axis=1,
    )

    scored = merged[merged["completion_rate"].notna() & merged["pipeline"].notna()]
    pipeline_median = float(scored["pipeline"].median()) if not scored.empty else 0.0
    delivery_median = float(scored["completion_rate"].median()) if not scored.empty else 0.0

    def quadrant(row) -> str:
        if pd.isna(row["pipeline"]) or row["work_orders"] == 0:
            return "Sales only - no delivery history"
        if pd.isna(row["completion_rate"]):
            return "Insufficient delivery data"
        strong_pipe = row["pipeline"] >= pipeline_median
        strong_del = row["completion_rate"] >= delivery_median
        if strong_pipe and strong_del:
            return "Scale"
        if strong_pipe and not strong_del:
            return "Fix delivery"
        if not strong_pipe and strong_del:
            return "Underinvested"
        return "Deprioritise"

    merged["quadrant"] = merged.apply(quadrant, axis=1)
    merged = merged.sort_values("pipeline", ascending=False, na_position="last")

    rows = [
        BreakdownRow(
            key=str(r["sector_norm"]), label=str(r["sector_norm"]),
            values={
                "pipeline": float(r["pipeline"]) if pd.notna(r["pipeline"]) else None,
                "completion_rate": (
                    float(r["completion_rate"]) if pd.notna(r["completion_rate"]) else None
                ),
                "work_orders": int(r["work_orders"]),
                "delayed": int(r["delayed"]),
                "open_deals": int(r["open_deals"]) if pd.notna(r.get("open_deals")) else 0,
            },
            display={
                "pipeline": format_inr(
                    float(r["pipeline"]) if pd.notna(r["pipeline"]) else None),
                "completion_rate": (
                    f"{float(r['completion_rate']):.0f}%"
                    if pd.notna(r["completion_rate"]) else "no delivery data"
                ),
                "work_orders": f"{int(r['work_orders']):,}",
                "delayed": f"{int(r['delayed']):,}",
                "quadrant": str(r["quadrant"]),
            },
        )
        for _, r in merged.iterrows()
    ]

    return Breakdown(
        key="sector_matrix",
        title="Sector opportunity vs execution",
        dimension="sector",
        columns=["pipeline", "completion_rate", "work_orders", "delayed", "quadrant"],
        rows=rows,
        chart="scatter",
        note=(
            "Quadrants are relative to the median sector on each axis "
            f"(pipeline {format_inr(pipeline_median)}, completion {delivery_median:.0f}%). "
            "Sectors present on only one board are labelled rather than scored."
        ),
    )


def accounts_at_risk(
    deals: pd.DataFrame, work_orders: pd.DataFrame, limit: int = 10
) -> Breakdown:
    """Accounts carrying open pipeline AND delayed delivery.

    The commercially dangerous combination: we are trying to sell more to a
    customer we are currently letting down.
    """
    dg = _agg_deals_by_account(deals)
    wg = _agg_work_orders_by_account(work_orders)
    if dg.empty or wg.empty:
        return Breakdown(key="accounts_at_risk", title="Accounts with pipeline and delivery risk",
                         dimension="account",
                         columns=["open_pipeline", "delayed", "work_orders"], rows=[],
                         chart="table",
                         note="Both boards are required for this view.")

    merged = pd.merge(dg, wg, on="deal_name_norm", how="inner")
    at_risk = merged[(merged["delayed"] > 0) & (merged["open_deals"] > 0)]
    at_risk = at_risk.sort_values(
        ["delayed", "open_pipeline"], ascending=[False, False]
    ).head(limit)

    rows = [
        BreakdownRow(
            key=str(r["deal_name_norm"]),
            label=str(r["account_label"] or r["deal_name_norm"]),
            values={
                "open_pipeline": (
                    float(r["open_pipeline"]) if pd.notna(r["open_pipeline"]) else None
                ),
                "delayed": int(r["delayed"]),
                "work_orders": int(r["work_orders"]),
                "open_deals": int(r["open_deals"]),
            },
            display={
                "open_pipeline": format_inr(
                    float(r["open_pipeline"]) if pd.notna(r["open_pipeline"]) else None),
                "delayed": f"{int(r['delayed'])} delayed",
                "work_orders": f"{int(r['work_orders'])} work orders",
                "open_deals": f"{int(r['open_deals'])} open deals",
            },
        )
        for _, r in at_risk.iterrows()
    ]
    return Breakdown(
        key="accounts_at_risk",
        title="Accounts with open pipeline and delivery risk",
        dimension="account",
        columns=["open_pipeline", "open_deals", "work_orders", "delayed"],
        rows=rows, chart="table",
        note=(
            "Accounts are matched on deal/account name across the two boards. "
            "Customer codes cannot be used: the boards mask customers differently."
        ),
    )


def won_vs_delivered_by_sector(
    deals: pd.DataFrame, work_orders: pd.DataFrame
) -> Breakdown:
    """Are we winning more in a sector than we are finishing?"""
    if deals.empty or work_orders.empty:
        return Breakdown(key="won_vs_delivered", title="Deals won vs work delivered",
                         dimension="sector", columns=["won_deals", "completed"],
                         rows=[], chart="bar",
                         note="Both boards are required for this view.")

    dg = deals.groupby("sector_norm", dropna=True).agg(
        won_deals=("is_won", "sum")).reset_index()
    wg = work_orders.groupby("sector_norm", dropna=True).agg(
        completed=("is_complete", "sum"),
        work_orders=("wo_id", "size")).reset_index()
    merged = pd.merge(dg, wg, on="sector_norm", how="inner")
    merged = merged.sort_values("won_deals", ascending=False)

    rows = [
        BreakdownRow(
            key=str(r["sector_norm"]), label=str(r["sector_norm"]),
            values={
                "won_deals": int(r["won_deals"]),
                "completed": int(r["completed"]),
                "work_orders": int(r["work_orders"]),
                "ratio": (
                    float(r["completed"]) / int(r["won_deals"]) if r["won_deals"] else None
                ),
            },
            display={
                "won_deals": f"{int(r['won_deals']):,}",
                "completed": f"{int(r['completed']):,}",
                "work_orders": f"{int(r['work_orders']):,}",
                "ratio": (
                    f"{float(r['completed']) / int(r['won_deals']):.2f}x"
                    if r["won_deals"] else "-"
                ),
            },
        )
        for _, r in merged.iterrows()
    ]
    return Breakdown(
        key="won_vs_delivered", title="Deals won vs work orders delivered, by sector",
        dimension="sector",
        columns=["won_deals", "work_orders", "completed", "ratio"],
        rows=rows, chart="bar",
        note=(
            "Deals and work orders are not one-to-one -- a single won deal can "
            "generate several work orders -- so read the ratio as a direction of "
            "travel, not a conversion rate."
        ),
    )


def owner_sales_vs_delivery(
    deals: pd.DataFrame, work_orders: pd.DataFrame
) -> Breakdown:
    """Owner codes are shared across boards, so this join is exact."""
    if deals.empty or work_orders.empty:
        return Breakdown(key="owner_cross", title="Owner: pipeline vs delivery",
                         dimension="owner", columns=["pipeline", "delayed"],
                         rows=[], chart="table",
                         note="Both boards are required for this view.")
    d = deals.copy()
    d["_open_amt"] = pd.to_numeric(d["amount_value"], errors="coerce").where(
        d["is_open"] == True)  # noqa: E712
    dg = d.groupby("owner_code", dropna=True).agg(
        pipeline=("_open_amt", "sum"), open_deals=("is_open", "sum")).reset_index()
    wg = work_orders.groupby("owner_code", dropna=True).agg(
        work_orders=("wo_id", "size"), delayed=("is_delayed", "sum"),
        completed=("is_complete", "sum")).reset_index()
    merged = pd.merge(dg, wg, on="owner_code", how="outer").fillna(
        {"work_orders": 0, "delayed": 0, "completed": 0, "open_deals": 0})
    merged = merged[merged["owner_code"].notna()].sort_values(
        "pipeline", ascending=False, na_position="last")

    rows = [
        BreakdownRow(
            key=str(r["owner_code"]), label=str(r["owner_code"]),
            values={
                "pipeline": float(r["pipeline"]) if pd.notna(r["pipeline"]) else None,
                "open_deals": int(r["open_deals"]),
                "work_orders": int(r["work_orders"]),
                "delayed": int(r["delayed"]),
            },
            display={
                "pipeline": format_inr(
                    float(r["pipeline"]) if pd.notna(r["pipeline"]) else None),
                "open_deals": f"{int(r['open_deals']):,}",
                "work_orders": f"{int(r['work_orders']):,}",
                "delayed": f"{int(r['delayed']):,}",
            },
        )
        for _, r in merged.iterrows()
    ]
    return Breakdown(key="owner_cross", title="Owner: pipeline vs delivery",
                     dimension="owner",
                     columns=["pipeline", "open_deals", "work_orders", "delayed"],
                     rows=rows, chart="table")


def customer_join_unavailable_note() -> str:
    """Returned whenever a user asks for customer-level cross-board analysis."""
    return (
        "Customer-level comparison across the two boards is not possible with this "
        "data: the Deals board masks customers as COMPANY### and the Work Orders "
        "board masks them as WOCOMPANY_###, with no overlap between the two "
        "schemes. I can compare by account/deal name, sector or owner instead, "
        "all of which do join reliably."
    )
