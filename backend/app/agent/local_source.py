"""Development-only data source: the cleaned CSVs in data_clean/.

WHY THIS EXISTS
    The Monday.com integration is the real path and the default. This module
    exists so the analytics, agent and UI layers can be built and demonstrated
    while the boards are still being imported, and as a safety net if the
    Monday workspace is unreachable during a live demo.

WHAT IT IS NOT
    It is not a mock of the Monday API and it never fabricates records. It reads
    the same source spreadsheets, runs them through the same normalization
    pipeline, and every response it produces carries a visible warning that the
    data is local rather than live.

Activated only by DATA_SOURCE=local_csv.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..data import pipeline as pl
from ..models.schemas import Board, BoardStatus

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data_clean"

LOCAL_WARNING = (
    "Running on local CSV data (DATA_SOURCE=local_csv), not live Monday.com data."
)

# Source CSV header -> canonical field name. Mirrors the Monday column alias
# table so both paths converge on the same canonical schema.
DEALS_MAP = {
    "Deal Name": "deal_name", "Owner code": "owner_code", "Client Code": "client_code",
    "Deal Status": "status", "Deal Stage": "stage", "Sector/service": "sector",
    "Masked Deal value": "amount", "Closure Probability": "probability",
    "Tentative Close Date": "tentative_close_date",
    "Close Date (A)": "actual_close_date", "Created Date": "created_date",
    "Product deal": "product",
}

WORK_ORDERS_MAP = {
    "Deal name masked": "deal_name", "Serial #": "wo_id",
    "Customer Name Code": "customer_code", "Sector": "sector",
    "Execution Status": "exec_status", "Nature of Work": "nature_of_work",
    "Type of Work": "type_of_work", "BD/KAM Personnel code": "owner_code",
    "Probable Start Date": "start_date", "Probable End Date": "end_date",
    "Data Delivery Date": "delivery_date", "Date of PO/LOI": "po_date",
    "Document Type": "document_type",
    "Amount in Rupees (Excl of GST) (Masked)": "amount_excl_gst",
    "Amount in Rupees (Incl of GST) (Masked)": "amount_incl_gst",
    "Billed Value in Rupees (Excl of GST.) (Masked)": "billed_value",
    "Amount Receivable (Masked)": "receivable", "Invoice Status": "invoice_status",
    "WO Status (billed)": "wo_status",
}

_FILES = {
    Board.DEALS: ("deals_clean.csv", DEALS_MAP),
    Board.WORK_ORDERS: ("work_orders_clean.csv", WORK_ORDERS_MAP),
}


def load_local_board(board: Board):
    from .executor import BoardData  # imported here to avoid a circular import

    filename, mapping = _FILES[board]
    path = DATA_DIR / filename
    empty = (
        pl.empty_deals_frame() if board == Board.DEALS else pl.empty_work_orders_frame()
    )
    blank_report = {"board": board.value, "rows_in": 0, "rows_out": 0,
                    "header_echo_dropped": 0, "injection_suspects": 0, "flags": {}}

    if not path.exists():
        message = (
            f"Local data file not found: {path}. "
            "Run `python scripts/prepare_for_monday.py` first."
        )
        logger.error(message)
        return BoardData(empty, blank_report,
                         BoardStatus(name=board.value, error=message), error=message)

    raw = pd.read_csv(path).rename(columns=mapping)
    if board == Board.DEALS:
        frame, report = pl.normalize_deals(raw)
    else:
        frame, report = pl.normalize_work_orders(raw)

    status = BoardStatus(
        name=f"{board.value.replace('_', ' ').title()} (local CSV)",
        board_id=None,
        item_count=len(frame),
        fetched_at=None,
        age_seconds=None,
    )
    return BoardData(frame, report.as_dict(), status, error=LOCAL_WARNING)
