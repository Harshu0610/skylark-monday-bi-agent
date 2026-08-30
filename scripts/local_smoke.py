"""Offline smoke test: run the full analytics stack against the local CSVs.

This exercises normalization -> metrics -> ledger without needing Monday.com or
an LLM key. It maps the cleaned CSV columns onto the same canonical field names
the Monday column resolver produces, so the code path under test is the real one.

Usage:
    python scripts/local_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analytics.registry import run_analysis  # noqa: E402
from app.data.pipeline import normalize_deals, normalize_work_orders  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Board, DatePreset, DateRange, Filters, Intent, QueryPlan,
)

DEALS_MAP = {
    "Deal Name": "deal_name",
    "Owner code": "owner_code",
    "Client Code": "client_code",
    "Deal Status": "status",
    "Deal Stage": "stage",
    "Sector/service": "sector",
    "Masked Deal value": "amount",
    "Closure Probability": "probability",
    "Tentative Close Date": "tentative_close_date",
    "Close Date (A)": "actual_close_date",
    "Created Date": "created_date",
    "Product deal": "product",
}

WO_MAP = {
    "Deal name masked": "deal_name",
    "Serial #": "wo_id",
    "Customer Name Code": "customer_code",
    "Sector": "sector",
    "Execution Status": "exec_status",
    "Nature of Work": "nature_of_work",
    "Type of Work": "type_of_work",
    "BD/KAM Personnel code": "owner_code",
    "Probable Start Date": "start_date",
    "Probable End Date": "end_date",
    "Data Delivery Date": "delivery_date",
    "Date of PO/LOI": "po_date",
    "Document Type": "document_type",
    "Amount in Rupees (Excl of GST) (Masked)": "amount_excl_gst",
    "Amount in Rupees (Incl of GST) (Masked)": "amount_incl_gst",
    "Billed Value in Rupees (Excl of GST.) (Masked)": "billed_value",
    "Amount Receivable (Masked)": "receivable",
    "Invoice Status": "invoice_status",
    "WO Status (billed)": "wo_status",
}


def load() -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    deals_raw = pd.read_csv(ROOT / "data_clean" / "deals_clean.csv").rename(columns=DEALS_MAP)
    wo_raw = pd.read_csv(ROOT / "data_clean" / "work_orders_clean.csv").rename(columns=WO_MAP)
    deals, d_report = normalize_deals(deals_raw)
    work_orders, w_report = normalize_work_orders(wo_raw)
    return deals, work_orders, [d_report.as_dict(), w_report.as_dict()]


def show(title: str, plan: QueryPlan, deals, work_orders, reports) -> None:
    result = run_analysis(plan, deals, work_orders, reports)
    print("=" * 78)
    print(title)
    print("=" * 78)
    if result.unsupported:
        print("UNSUPPORTED:", result.unsupported)
        return
    for m in result.metrics:
        line = f"  {m.label:<38} {m.display:>18}"
        if m.rows_excluded:
            line += f"   [{m.rows_included}/{m.rows_considered} rows]"
        print(line)
        if m.note:
            print(f"      note: {m.note}")
    for b in result.breakdowns:
        if not b.rows:
            continue
        print(f"  -- {b.title}")
        for row in b.rows[:6]:
            bits = " | ".join(f"{k}={v}" for k, v in list(row.display.items())[:4])
            print(f"       {row.label:<34} {bits}")
    print(f"  ledger: confidence={result.ledger.confidence} "
          f"included={result.ledger.rows_included}/{result.ledger.rows_considered}")
    for note in result.ledger.notes:
        print(f"      * {note}")
    for caveat in result.caveats:
        print(f"      ! {caveat}")
    print()


def main() -> int:
    deals, work_orders, reports = load()
    print(f"Loaded {len(deals)} deals, {len(work_orders)} work orders\n")

    cases = [
        ("TOTAL PIPELINE", QueryPlan(intent=Intent.PIPELINE, boards=[Board.DEALS])),
        ("PIPELINE THIS QUARTER", QueryPlan(
            intent=Intent.PIPELINE, boards=[Board.DEALS],
            filters=Filters(date_range=DateRange(preset=DatePreset.THIS_QUARTER)))),
        ("ENERGY SECTOR (does not exist)", QueryPlan(
            intent=Intent.SECTOR_BREAKDOWN, boards=[Board.DEALS],
            filters=Filters(sector="Energy"))),
        ("MINING SECTOR", QueryPlan(
            intent=Intent.SECTOR_BREAKDOWN, boards=[Board.DEALS],
            filters=Filters(sector="Mining"))),
        ("WON REVENUE", QueryPlan(intent=Intent.WON_REVENUE, boards=[Board.DEALS])),
        ("DEAL RISK", QueryPlan(intent=Intent.DEAL_RISK, boards=[Board.DEALS])),
        ("DELAYED WORK", QueryPlan(intent=Intent.DELAYED_WORK, boards=[Board.WORK_ORDERS])),
        ("BILLING RISK", QueryPlan(intent=Intent.BILLING_RISK, boards=[Board.WORK_ORDERS])),
        ("CROSS-BOARD SECTOR", QueryPlan(
            intent=Intent.CROSS_BOARD_SECTOR, boards=[Board.DEALS, Board.WORK_ORDERS])),
        ("CROSS-BOARD ACCOUNTS", QueryPlan(
            intent=Intent.CROSS_BOARD_ACCOUNT, boards=[Board.DEALS, Board.WORK_ORDERS])),
        ("EXECUTIVE SUMMARY", QueryPlan(
            intent=Intent.EXECUTIVE_SUMMARY, boards=[Board.DEALS, Board.WORK_ORDERS])),
        ("DATA QUALITY", QueryPlan(
            intent=Intent.DATA_QUALITY, boards=[Board.DEALS, Board.WORK_ORDERS])),
    ]
    for title, plan in cases:
        show(title, plan, deals, work_orders, reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
