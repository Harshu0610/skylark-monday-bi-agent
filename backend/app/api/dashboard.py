"""Dedicated analytics & dashboard API endpoints for the redesigned UI."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal
from fastapi import APIRouter, Query

from ..agent.executor import DataService
from ..analytics import cross_board as cb
from ..analytics import executive as ex
from ..analytics import deals as dm
from ..analytics import work_orders as wm
from ..analytics.overview import SUGGESTED_QUESTIONS, build_overview
from ..analytics.registry import data_quality_report, fiscal_quarter_bounds
from ..config import get_settings
from ..data.quality import collect_flags, describe_flag
from ..models.schemas import Board, Intent, QueryPlan
from .chat import get_data_service

router = APIRouter()


def get_effective_today(deals: pd.DataFrame, work_orders: pd.DataFrame) -> date:
    """Returns effective date anchor: max date in historical data, or current date."""
    max_d = deals["created_date"].dropna().max() if not deals.empty and "created_date" in deals.columns else None
    max_w = work_orders["start_date"].dropna().max() if not work_orders.empty and "start_date" in work_orders.columns else None
    candidates = [c for c in (max_d, max_w) if c is not None]
    if candidates:
        max_dt = max(candidates)
        if max_dt < date.today():
            return max_dt
    return date.today()


@router.get("/overview")
async def get_overview() -> dict[str, Any]:
    """Provides high-level business pulse, real calculated KPI cards, and operational alerts."""
    service: DataService = get_data_service()
    bundle = await service.load([Board.DEALS, Board.WORK_ORDERS])
    effective_today = get_effective_today(bundle.deals, bundle.work_orders)

    overview_data = build_overview(bundle.deals, bundle.work_orders, effective_today)
    overview_data["suggested_questions"] = SUGGESTED_QUESTIONS
    overview_data["data_source"] = get_settings().data_source
    overview_data["warnings"] = bundle.warnings
    return overview_data


@router.get("/data-quality")
async def get_data_quality() -> dict[str, Any]:
    """Comprehensive data quality diagnostics, health score, flags, and missing values."""
    service: DataService = get_data_service()
    bundle = await service.load([Board.DEALS, Board.WORK_ORDERS])
    
    plan = QueryPlan(intent=Intent.DATA_QUALITY, boards=[Board.DEALS, Board.WORK_ORDERS])
    report = data_quality_report(plan, bundle.deals, bundle.work_orders, bundle.reports)

    deals_total = len(bundle.deals)
    wo_total = len(bundle.work_orders)
    total_records = deals_total + wo_total

    # Compute high-level usable records score
    deals_clean = int(bundle.deals["amount_value"].notna().sum()) if not bundle.deals.empty else 0
    wo_clean = int(bundle.work_orders["end_date"].notna().sum()) if not bundle.work_orders.empty else 0
    clean_records = deals_clean + wo_clean
    health_score = round((clean_records / total_records * 100), 1) if total_records else 100.0

    # Cross-board coverage
    coverage_metric = cb.account_link_coverage(bundle.deals, bundle.work_orders)

    # Detailed column missing stats
    deals_missing = {}
    if not bundle.deals.empty:
        for col in ["amount_value", "tentative_close_date", "actual_close_date", "probability_weight", "owner_code", "sector_norm"]:
            if col in bundle.deals.columns:
                deals_missing[col] = int(bundle.deals[col].isna().sum())

    wo_missing = {}
    if not bundle.work_orders.empty:
        for col in ["end_date", "start_date", "amount_excl_gst", "billed_value", "invoice_status", "customer_code"]:
            if col in bundle.work_orders.columns:
                wo_missing[col] = int(bundle.work_orders[col].isna().sum())

    deals_flags = collect_flags(bundle.deals) if not bundle.deals.empty else {}
    wo_flags = collect_flags(bundle.work_orders) if not bundle.work_orders.empty else {}

    return {
        "health_score": health_score,
        "total_records": total_records,
        "deals_count": deals_total,
        "work_orders_count": wo_total,
        "metrics": [m.model_dump() for m in report.metrics],
        "breakdowns": [b.model_dump() for b in report.breakdowns],
        "ledger": report.ledger.model_dump(),
        "coverage": coverage_metric.model_dump(),
        "deals_missing": deals_missing,
        "wo_missing": wo_missing,
        "deals_flags": [{"flag": f, "label": describe_flag(f), "count": c} for f, c in sorted(deals_flags.items(), key=lambda x: -x[1])],
        "wo_flags": [{"flag": f, "label": describe_flag(f), "count": c} for f, c in sorted(wo_flags.items(), key=lambda x: -x[1])],
        "caveats": report.caveats,
        "normalization_reports": bundle.reports,
    }


@router.get("/insights")
async def get_insights() -> dict[str, Any]:
    """Cross-board strategic matrix, accounts-at-risk, owner comparisons, and won vs delivered ratios."""
    service: DataService = get_data_service()
    bundle = await service.load([Board.DEALS, Board.WORK_ORDERS])

    sector_matrix = cb.sector_opportunity_matrix(bundle.deals, bundle.work_orders)
    accounts_risk = cb.accounts_at_risk(bundle.deals, bundle.work_orders, limit=15)
    owner_cross = cb.owner_sales_vs_delivery(bundle.deals, bundle.work_orders)
    won_vs_del = cb.won_vs_delivered_by_sector(bundle.deals, bundle.work_orders)
    coverage = cb.account_link_coverage(bundle.deals, bundle.work_orders)

    return {
        "sector_matrix": sector_matrix.model_dump(),
        "accounts_at_risk": accounts_risk.model_dump(),
        "owner_cross": owner_cross.model_dump(),
        "won_vs_delivered": won_vs_del.model_dump(),
        "coverage": coverage.model_dump(),
        "customer_join_note": cb.customer_join_unavailable_note(),
    }


@router.get("/reports")
async def get_reports(quarter_offset: int = 0) -> dict[str, Any]:
    """Leadership briefing, talking points, quarterly funnel comparisons, and ranked risks."""
    service: DataService = get_data_service()
    bundle = await service.load([Board.DEALS, Board.WORK_ORDERS])
    effective_today = get_effective_today(bundle.deals, bundle.work_orders)

    (this_start, this_end, this_label), (last_start, last_end, last_label), shifted = (
        ex.latest_populated_quarters(bundle.deals, effective_today)
    )
    if quarter_offset != 0:
        this_start, this_end, this_label = fiscal_quarter_bounds(effective_today, quarter_offset)
        last_start, last_end, last_label = fiscal_quarter_bounds(effective_today, quarter_offset - 1)

    # Core metrics
    pipeline = dm.total_open_pipeline(bundle.deals)
    weighted = dm.weighted_pipeline(bundle.deals)
    created, prior, change = ex.quarter_over_quarter(
        bundle.deals, this_start, this_end, this_label, last_start, last_end, last_label
    )
    won = dm.won_revenue(bundle.deals)
    win = dm.win_rate(bundle.deals)
    active = wm.active_work_orders(bundle.work_orders)
    completion = wm.completion_rate(bundle.work_orders)
    delayed = wm.delayed_work_orders(bundle.work_orders)
    backlog = wm.overdue_backlog_value(bundle.work_orders)
    unbilled = wm.unbilled_completed(bundle.work_orders)
    stale = dm.stale_deal_value(bundle.deals)
    conc = dm.pipeline_concentration(bundle.deals)
    open_count = dm.open_deal_count(bundle.deals)

    metrics_list = [
        pipeline, weighted, created, prior, change, won, win,
        active, completion, delayed, backlog, unbilled, stale, conc, open_count
    ]

    sector_matrix = cb.sector_opportunity_matrix(bundle.deals, bundle.work_orders)
    accounts_risk = cb.accounts_at_risk(bundle.deals, bundle.work_orders)
    pipeline_sector = dm.pipeline_by_sector(bundle.deals)
    funnel_stage = dm.pipeline_by_stage(bundle.deals)
    quarter_series = ex.pipeline_created_by_quarter(bundle.deals, effective_today, quarters=4)

    breakdowns_list = [sector_matrix, accounts_risk, pipeline_sector]
    risks, points, briefing = ex.build_briefing(metrics_list, breakdowns_list, this_label)

    return {
        "period_label": this_label,
        "prior_period_label": last_label,
        "talking_points": points,
        "ranked_risks": risks,
        "briefing_breakdown": briefing.model_dump(),
        "metrics": [m.model_dump() for m in metrics_list],
        "quarterly_trend": quarter_series.model_dump(),
        "funnel_stage": funnel_stage.model_dump(),
        "sector_matrix": sector_matrix.model_dump(),
    }


@router.get("/records")
async def get_records(
    board: Literal["deals", "work_orders"] = "deals",
    query: str | None = None,
    filter_status: str | None = None,
    filter_sector: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Retrieve normalized records for interactive data drill-downs and table inspection."""
    service: DataService = get_data_service()
    b_enum = Board.DEALS if board == "deals" else Board.WORK_ORDERS
    bundle = await service.load([b_enum])
    df = bundle.deals if board == "deals" else bundle.work_orders

    if df.empty:
        return {"board": board, "total": 0, "records": []}

    filtered = df.copy()

    if filter_sector:
        filtered = filtered[filtered["sector_norm"].fillna("").str.lower() == filter_sector.lower()]

    if filter_status:
        col = "status_norm" if board == "deals" else "exec_status_norm"
        if col in filtered.columns:
            filtered = filtered[filtered[col].fillna("").str.lower() == filter_status.lower()]

    if query:
        q = query.lower()
        search_cols = ["deal_name_raw", "owner_code", "sector_norm"]
        if board == "work_orders":
            search_cols.extend(["wo_id", "customer_code"])
        
        mask = filtered[search_cols[0]].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        for c in search_cols[1:]:
            if c in filtered.columns:
                mask = mask | filtered[c].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        filtered = filtered[mask]

    total = len(filtered)
    page = filtered.iloc[offset : offset + limit]

    records = []
    for _, row in page.iterrows():
        rec = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                rec[k] = v.isoformat()
            elif isinstance(v, float) and (v != v):
                rec[k] = None
            else:
                rec[k] = v
        records.append(rec)

    return {
        "board": board,
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": records,
    }

