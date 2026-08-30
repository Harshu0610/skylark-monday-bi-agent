"""Resolve boards by name and map Monday column titles to canonical field names.

Two robustness decisions worth noting:

1. Boards are found by NAME, not a hardcoded ID. Re-importing a board changes
   its ID; it rarely changes its name.
2. Columns are matched through an ALIAS table, so renaming "Masked Deal value"
   to "Deal Value" in Monday does not break the app. Unmatched required columns
   degrade the answer instead of crashing it.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .client import MondayBoardNotFoundError, MondayClient

logger = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


# canonical field -> accepted Monday column titles (first match wins)
DEALS_COLUMN_ALIASES: dict[str, list[str]] = {
    "deal_name": ["Deal Name", "Name", "Deal"],
    "owner_code": ["Owner code", "Owner", "Owner Code", "BD Owner"],
    "client_code": ["Client Code", "Client", "Customer Code"],
    "status": ["Deal Status", "Status"],
    "stage": ["Deal Stage", "Stage"],
    "sector": ["Sector/service", "Sector", "Sector / Service", "Sector service"],
    "amount": ["Masked Deal value", "Deal Value", "Amount", "Value", "Deal value"],
    "probability": ["Closure Probability", "Probability", "Close Probability"],
    "tentative_close_date": ["Tentative Close Date", "Expected Close Date", "Close Date"],
    "actual_close_date": ["Close Date (A)", "Actual Close Date", "Close Date A"],
    "created_date": ["Created Date", "Created", "Creation Date"],
    "product": ["Product deal", "Product", "Product Deal"],
}

WORK_ORDER_COLUMN_ALIASES: dict[str, list[str]] = {
    "deal_name": ["Deal name masked", "Deal Name", "Name", "Deal"],
    "wo_id": ["Serial #", "Serial No", "Serial", "WO ID", "Work Order ID"],
    "customer_code": ["Customer Name Code", "Customer Code", "Customer", "Client Code"],
    "sector": ["Sector", "Sector/service"],
    "exec_status": ["Execution Status", "Status", "Execution"],
    "nature_of_work": ["Nature of Work", "Nature", "Work Nature"],
    "type_of_work": ["Type of Work", "Work Type", "Type"],
    "owner_code": ["BD/KAM Personnel code", "BD/KAM Personnel", "Owner code", "Owner"],
    "start_date": ["Probable Start Date", "Start Date", "Planned Start"],
    "end_date": ["Probable End Date", "End Date", "Planned End", "Due Date"],
    "delivery_date": ["Data Delivery Date", "Delivery Date", "Delivered On"],
    "po_date": ["Date of PO/LOI", "PO Date", "Date of PO"],
    "document_type": ["Document Type", "Doc Type"],
    "amount_excl_gst": [
        "Amount in Rupees (Excl of GST) (Masked)",
        "Amount Excl GST",
        "Amount (Excl GST)",
        "Amount",
    ],
    "amount_incl_gst": [
        "Amount in Rupees (Incl of GST) (Masked)",
        "Amount Incl GST",
        "Amount (Incl GST)",
    ],
    "billed_value": [
        "Billed Value in Rupees (Excl of GST.) (Masked)",
        "Billed Value",
        "Billed",
    ],
    "receivable": ["Amount Receivable (Masked)", "Amount Receivable", "Receivable"],
    "invoice_status": ["Invoice Status", "Invoicing Status"],
    "wo_status": ["WO Status (billed)", "WO Status", "Work Order Status"],
}

# Fields without which a board is not usable at all.
DEALS_REQUIRED = ["deal_name", "status", "stage", "sector", "amount"]
WORK_ORDERS_REQUIRED = ["deal_name", "wo_id", "sector", "exec_status"]


class ResolvedBoard:
    def __init__(
        self,
        board_id: str,
        name: str,
        item_count: int,
        column_map: dict[str, str],
        missing_fields: list[str],
    ) -> None:
        self.board_id = board_id
        self.name = name
        self.item_count = item_count
        self.column_map = column_map          # canonical field -> monday column id
        self.missing_fields = missing_fields  # canonical fields with no column


def build_column_map(
    columns: list[dict[str, Any]], aliases: dict[str, list[str]]
) -> tuple[dict[str, str], list[str]]:
    """Map canonical field names onto Monday column ids via the alias table."""
    by_slug: dict[str, str] = {}
    for col in columns:
        by_slug.setdefault(_slug(col.get("title", "")), col.get("id", ""))

    mapping: dict[str, str] = {}
    missing: list[str] = []
    for field, candidates in aliases.items():
        for candidate in candidates:
            col_id = by_slug.get(_slug(candidate))
            if col_id:
                mapping[field] = col_id
                break
        else:
            missing.append(field)
    return mapping, missing


async def resolve_board(
    client: MondayClient,
    *,
    explicit_id: str | None,
    board_name: str,
    aliases: dict[str, list[str]],
    required: list[str],
) -> ResolvedBoard:
    board_id = explicit_id
    if not board_id:
        boards = await client.list_boards()
        target = _slug(board_name)
        match = next((b for b in boards if _slug(b.get("name", "")) == target), None)
        if match is None:
            # Fall back to a contains match before giving up -- users name boards
            # things like "Deals (imported)".
            match = next((b for b in boards if target in _slug(b.get("name", ""))), None)
        if match is None:
            available = ", ".join(b.get("name", "?") for b in boards[:15]) or "none"
            raise MondayBoardNotFoundError(
                f"No board named '{board_name}'. Boards visible to this token: {available}"
            )
        board_id = str(match["id"])

    detail = await client.get_board_columns(board_id)
    column_map, missing = build_column_map(detail.get("columns") or [], aliases)

    missing_required = [f for f in required if f in missing]
    if missing_required:
        logger.warning(
            "board %s is missing required fields: %s", detail.get("name"), missing_required
        )

    return ResolvedBoard(
        board_id=str(detail.get("id", board_id)),
        name=detail.get("name", board_name),
        item_count=int(detail.get("items_count") or 0),
        column_map=column_map,
        missing_fields=missing,
    )
