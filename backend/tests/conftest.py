"""Shared fixtures.

`fixture_deals` / `fixture_work_orders` are small hand-built frames with known
answers, so metric assertions are exact rather than approximate. `real_*` load
the actual Skylark spreadsheets when present, to catch problems that only show
up against messy production-shaped data.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.data.pipeline import normalize_deals, normalize_work_orders  # noqa: E402

TODAY = date(2026, 8, 30)


@pytest.fixture
def raw_deals() -> pd.DataFrame:
    """Six deals with deliberately known totals.

    Open deals with values : 1,000,000 + 500,000            = 1,500,000
    Open deals total       : 3 (one has no value)
    Won                    : 2 (one valued 2,000,000, one blank)
    Lost                   : 1
    Win rate               : 2 won / 3 closed             = 66.67%
    """
    return pd.DataFrame([
        {"deal_name": "Alpha", "status": "Open", "stage": "F. Negotiations",
         "sector": "Mining", "amount": 1_000_000, "probability": "High",
         "tentative_close_date": "2026-09-15", "created_date": "2026-01-15",
         "owner_code": "OWNER_001", "client_code": "COMPANY001"},
        {"deal_name": "Beta", "status": "Open", "stage": "E. Proposal/Commercials Sent",
         "sector": "Renewables", "amount": 500_000, "probability": "Medium",
         "tentative_close_date": "2026-07-01", "created_date": "2026-02-01",
         "owner_code": "OWNER_002", "client_code": "COMPANY002"},
        {"deal_name": "Gamma", "status": "Open", "stage": "A. Lead Generated",
         "sector": "Mining", "amount": None, "probability": None,
         "tentative_close_date": None, "created_date": "2026-03-01",
         "owner_code": "OWNER_001", "client_code": "COMPANY003"},
        {"deal_name": "Delta", "status": "Won", "stage": "G. Project Won",
         "sector": "Railways", "amount": 2_000_000, "probability": None,
         "tentative_close_date": "2026-05-01", "created_date": "2025-11-01",
         "owner_code": "OWNER_002", "client_code": "COMPANY004"},
        {"deal_name": "Epsilon", "status": "Won", "stage": "Project Completed",
         "sector": "Railways", "amount": None, "probability": None,
         "tentative_close_date": "2026-04-01", "created_date": "2025-10-01",
         "owner_code": "OWNER_003", "client_code": "COMPANY005"},
        {"deal_name": "Zeta", "status": "Dead", "stage": "L. Project Lost",
         "sector": "Mining", "amount": 300_000, "probability": None,
         "tentative_close_date": "2026-02-01", "created_date": "2025-09-01",
         "owner_code": "OWNER_001", "client_code": "COMPANY006"},
    ])


@pytest.fixture
def raw_work_orders() -> pd.DataFrame:
    """Five work orders.

    Completed : 2 (one via "Executed until current month")
    Delayed   : 1 (Delta - past end date, still Ongoing)
    No end date and incomplete : 1 (Epsilon - delay undeterminable)
    """
    past = (TODAY - timedelta(days=30)).isoformat()
    future = (TODAY + timedelta(days=30)).isoformat()
    return pd.DataFrame([
        {"deal_name": "Alpha", "wo_id": "WO-1", "customer_code": "WOCOMPANY_001",
         "sector": "Mining", "exec_status": "Completed", "start_date": "2026-01-01",
         "end_date": past, "delivery_date": "2026-02-10", "amount_excl_gst": 400_000,
         "billed_value": 400_000, "invoice_status": "Fully Billed",
         "owner_code": "OWNER_001", "nature_of_work": "One time Project"},
        {"deal_name": "Beta", "wo_id": "WO-2", "customer_code": "WOCOMPANY_002",
         "sector": "Renewables", "exec_status": "Executed until current month",
         "start_date": "2026-01-01", "end_date": future, "delivery_date": None,
         "amount_excl_gst": 600_000, "billed_value": 100_000,
         "invoice_status": "Partially Billed", "owner_code": "OWNER_002",
         "nature_of_work": "Monthly Contract"},
        {"deal_name": "Delta", "wo_id": "WO-3", "customer_code": "WOCOMPANY_003",
         "sector": "Railways", "exec_status": "Ongoing", "start_date": "2026-01-01",
         "end_date": past, "delivery_date": None, "amount_excl_gst": 900_000,
         "billed_value": None, "invoice_status": None, "owner_code": "OWNER_002",
         "nature_of_work": "One time Project"},
        {"deal_name": "Epsilon", "wo_id": "WO-4", "customer_code": "WOCOMPANY_004",
         "sector": "Railways", "exec_status": "Not Started", "start_date": None,
         "end_date": None, "delivery_date": None, "amount_excl_gst": 200_000,
         "billed_value": None, "invoice_status": "Not billed yet",
         "owner_code": "OWNER_003", "nature_of_work": "Proof of Concept"},
        {"deal_name": "Orphan", "wo_id": "WO-5", "customer_code": "WOCOMPANY_005",
         "sector": "Mining", "exec_status": "Completed", "start_date": "2026-02-01",
         "end_date": future, "delivery_date": "2026-03-03", "amount_excl_gst": None,
         "billed_value": None, "invoice_status": "Not billed yet",
         "owner_code": "OWNER_004", "nature_of_work": "One time Project"},
    ])


@pytest.fixture
def deals(raw_deals):
    frame, _ = normalize_deals(raw_deals, today=TODAY)
    return frame


@pytest.fixture
def work_orders(raw_work_orders):
    frame, _ = normalize_work_orders(raw_work_orders, today=TODAY)
    return frame


@pytest.fixture
def reports(raw_deals, raw_work_orders):
    _, d = normalize_deals(raw_deals, today=TODAY)
    _, w = normalize_work_orders(raw_work_orders, today=TODAY)
    return [d.as_dict(), w.as_dict()]


@pytest.fixture
def empty_deals():
    from app.data.pipeline import empty_deals_frame
    return empty_deals_frame()


@pytest.fixture
def empty_work_orders():
    from app.data.pipeline import empty_work_orders_frame
    return empty_work_orders_frame()
