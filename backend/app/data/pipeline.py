"""Raw Monday.com items -> canonical DataFrames + a data-quality ledger.

Every row keeps its raw value alongside the normalized one, and every
transformation is counted. That accounting is what lets the agent say
"87 of 93 deals included, 6 excluded for missing amounts" instead of just
emitting a number and hoping.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from typing import Any

import pandas as pd

from . import normalizers as nz

logger = logging.getLogger(__name__)


class NormalizationReport:
    """Counters accumulated while building a canonical frame."""

    def __init__(self, board: str) -> None:
        self.board = board
        self.rows_in = 0
        self.rows_out = 0
        self.header_echo_dropped = 0
        self.flags: Counter[str] = Counter()
        self.injection_suspects = 0

    def record(self, flags: list[str]) -> None:
        for flag in flags:
            self.flags[flag] += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "board": self.board,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "header_echo_dropped": self.header_echo_dropped,
            "injection_suspects": self.injection_suspects,
            "flags": dict(self.flags),
        }


# ---------------------------------------------------------------------------
# Monday item unpacking
# ---------------------------------------------------------------------------

def item_to_record(item: dict[str, Any], column_map: dict[str, str]) -> dict[str, Any]:
    """Flatten one Monday item into {canonical_field: text_value}.

    Monday returns both `text` (human readable) and `value` (typed JSON). We use
    `text` -- it is what the user sees in the board, which keeps the ledger
    honest -- and fall back to the item name for the name field.
    """
    by_column_id = {cv.get("id"): cv for cv in (item.get("column_values") or [])}
    record: dict[str, Any] = {"_monday_id": item.get("id")}

    for field, col_id in column_map.items():
        cv = by_column_id.get(col_id)
        record[field] = cv.get("text") if cv else None

    # The item name is the board's title column and is not in column_values.
    if not record.get("deal_name"):
        record["deal_name"] = item.get("name")
    return record


def items_to_frame(
    items: list[dict[str, Any]], column_map: dict[str, str]
) -> pd.DataFrame:
    return pd.DataFrame([item_to_record(i, column_map) for i in items])


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------

DEAL_HEADER_ECHO_CHECKS = {
    "status": "Deal Status",
    "stage": "Deal Stage",
    "sector": "Sector/service",
    "deal_name": "Deal Name",
}


def normalize_deals(raw: pd.DataFrame, today: date | None = None) -> tuple[pd.DataFrame, NormalizationReport]:
    today = today or date.today()
    report = NormalizationReport("deals")
    report.rows_in = len(raw)
    rows: list[dict[str, Any]] = []

    for _, r in raw.iterrows():
        # Header-echo rows are artefacts of how these sheets were assembled.
        if any(
            nz.is_header_echo(r.get(field), header)
            for field, header in DEAL_HEADER_ECHO_CHECKS.items()
        ):
            report.header_echo_dropped += 1
            continue

        flags: list[str] = []

        status, f = nz.normalize_deal_status(r.get("status"))
        if f:
            flags.append(f)

        stage_label, stage_order, f = nz.normalize_stage(r.get("stage"))
        if f:
            flags.append(f)

        sector, f = nz.normalize_sector(r.get("sector"))
        if f:
            flags.append(f)

        amount, f = nz.parse_amount(r.get("amount"))
        if f:
            flags.append(f)

        prob_label, prob_weight, f = nz.normalize_probability(r.get("probability"), stage_order)
        if f:
            flags.append(f)

        tentative_close, f = nz.parse_date(r.get("tentative_close_date"))
        if f:
            flags.append(f"tentative_close_{f}")
        actual_close, f = nz.parse_date(r.get("actual_close_date"))
        if f:
            flags.append(f"actual_close_{f}")
        created, f = nz.parse_date(r.get("created_date"))
        if f:
            flags.append(f"created_{f}")

        deal_name = nz.clean_text(r.get("deal_name"))
        if nz.looks_like_injection(deal_name) or nz.looks_like_injection(r.get("sector")):
            report.injection_suspects += 1
            flags.append("suspicious_text")

        # Deal Status is the authoritative won/lost signal. The lettered stage
        # funnel is used for ordering only -- its letters do not line up
        # cleanly with outcome (e.g. "I. POC" sorts after "G. Project Won").
        is_won = status == "Won"
        is_lost = status == "Lost"
        is_open = status == "Open"
        is_on_hold = status == "OnHold"

        rows.append(
            {
                "monday_id": r.get("_monday_id"),
                "deal_name_raw": deal_name,
                "deal_name_norm": nz.normalize_entity_name(deal_name),
                "owner_code": nz.clean_text(r.get("owner_code")),
                "client_code": nz.clean_text(r.get("client_code")),
                "status_raw": nz.clean_text(r.get("status")),
                "status_norm": status,
                "stage_raw": nz.clean_text(r.get("stage")),
                "stage_norm": stage_label,
                "stage_order": stage_order,
                "sector_raw": nz.clean_text(r.get("sector")),
                "sector_norm": sector,
                "amount_raw": nz.clean_text(r.get("amount")),
                "amount_value": amount,
                "probability_raw": prob_label,
                "probability_weight": prob_weight,
                "tentative_close_date": tentative_close,
                "actual_close_date": actual_close,
                "created_date": created,
                "product": nz.clean_text(r.get("product")),
                "is_open": is_open,
                "is_won": is_won,
                "is_lost": is_lost,
                "is_on_hold": is_on_hold,
                "is_closed": is_won or is_lost,
                "age_days": (today - created).days if (created and is_open) else None,
                "is_stale": bool(
                    is_open and tentative_close and tentative_close < today
                ),
                "quality_flags": flags,
            }
        )
        report.record(flags)

    df = pd.DataFrame(rows)
    report.rows_out = len(df)
    return df, report


# ---------------------------------------------------------------------------
# Work Orders
# ---------------------------------------------------------------------------

WO_HEADER_ECHO_CHECKS = {
    "exec_status": "Execution Status",
    "sector": "Sector",
    "wo_id": "Serial #",
}


def normalize_work_orders(
    raw: pd.DataFrame, today: date | None = None
) -> tuple[pd.DataFrame, NormalizationReport]:
    today = today or date.today()
    report = NormalizationReport("work_orders")
    report.rows_in = len(raw)
    rows: list[dict[str, Any]] = []

    for _, r in raw.iterrows():
        if any(
            nz.is_header_echo(r.get(field), header)
            for field, header in WO_HEADER_ECHO_CHECKS.items()
        ):
            report.header_echo_dropped += 1
            continue

        flags: list[str] = []

        exec_status, f = nz.normalize_exec_status(r.get("exec_status"))
        if f:
            flags.append(f)

        sector, f = nz.normalize_sector(r.get("sector"))
        if f:
            flags.append(f)

        amount, f = nz.parse_amount(r.get("amount_excl_gst"))
        if f:
            flags.append(f"amount_excl_gst_{f}")
        amount_incl, _ = nz.parse_amount(r.get("amount_incl_gst"))
        billed, f = nz.parse_amount(r.get("billed_value"))
        if f == "amount_missing":
            flags.append("billed_value_missing")
        receivable, _ = nz.parse_amount(r.get("receivable"))

        start, f = nz.parse_date(r.get("start_date"))
        if f:
            flags.append(f"start_{f}")
        end, f = nz.parse_date(r.get("end_date"))
        if f:
            flags.append(f"end_{f}")
        delivery, f = nz.parse_date(r.get("delivery_date"))
        if f:
            flags.append(f"delivery_{f}")
        po_date, _ = nz.parse_date(r.get("po_date"))

        deal_name = nz.clean_text(r.get("deal_name"))
        if nz.looks_like_injection(deal_name) or nz.looks_like_injection(r.get("type_of_work")):
            report.injection_suspects += 1
            flags.append("suspicious_text")

        is_complete = exec_status == "Completed"
        is_active = exec_status in ("InProgress", "PartiallyComplete", "NotStarted")
        is_blocked = exec_status in ("Blocked", "Paused")

        # Delayed = planned end date has passed and the work is not complete.
        # Requires a planned end date; without one we cannot claim delay, so
        # those rows are excluded from the delay metric rather than assumed OK.
        if end is None or is_complete:
            is_delayed = False
            delay_days = None
            if end is None and not is_complete:
                flags.append("delay_undeterminable_no_end_date")
        else:
            is_delayed = end < today
            delay_days = (today - end).days if is_delayed else None

        duration_days = (
            (delivery - start).days if (delivery and start and delivery >= start) else None
        )

        rows.append(
            {
                "monday_id": r.get("_monday_id"),
                "wo_id": nz.clean_text(r.get("wo_id")),
                "deal_name_raw": deal_name,
                "deal_name_norm": nz.normalize_entity_name(deal_name),
                "customer_code": nz.clean_text(r.get("customer_code")),
                "owner_code": nz.clean_text(r.get("owner_code")),
                "sector_raw": nz.clean_text(r.get("sector")),
                "sector_norm": sector,
                "exec_status_raw": nz.clean_text(r.get("exec_status")),
                "exec_status_norm": exec_status,
                "nature_of_work": nz.clean_text(r.get("nature_of_work")),
                "type_of_work": nz.clean_text(r.get("type_of_work")),
                "document_type": nz.clean_text(r.get("document_type")),
                "invoice_status": nz.clean_text(r.get("invoice_status")),
                "wo_status": nz.clean_text(r.get("wo_status")),
                "start_date": start,
                "end_date": end,
                "delivery_date": delivery,
                "po_date": po_date,
                "amount_excl_gst": amount,
                "amount_incl_gst": amount_incl,
                "billed_value": billed,
                "receivable": receivable,
                "is_complete": is_complete,
                "is_active": is_active,
                "is_blocked": is_blocked,
                "is_delayed": is_delayed,
                "delay_days": delay_days,
                "duration_days": duration_days,
                "quality_flags": flags,
            }
        )
        report.record(flags)

    df = pd.DataFrame(rows)
    report.rows_out = len(df)
    return df, report


# ---------------------------------------------------------------------------
# Empty frames (used when a board is unreachable or empty)
# ---------------------------------------------------------------------------

DEAL_COLUMNS = [
    "monday_id", "deal_name_raw", "deal_name_norm", "owner_code", "client_code",
    "status_raw", "status_norm", "stage_raw", "stage_norm", "stage_order",
    "sector_raw", "sector_norm", "amount_raw", "amount_value", "probability_raw",
    "probability_weight", "tentative_close_date", "actual_close_date",
    "created_date", "product", "is_open", "is_won", "is_lost", "is_on_hold",
    "is_closed", "age_days", "is_stale", "quality_flags",
]

WORK_ORDER_COLUMNS = [
    "monday_id", "wo_id", "deal_name_raw", "deal_name_norm", "customer_code",
    "owner_code", "sector_raw", "sector_norm", "exec_status_raw",
    "exec_status_norm", "nature_of_work", "type_of_work", "document_type",
    "invoice_status", "wo_status", "start_date", "end_date", "delivery_date",
    "po_date", "amount_excl_gst", "amount_incl_gst", "billed_value",
    "receivable", "is_complete", "is_active", "is_blocked", "is_delayed",
    "delay_days", "duration_days", "quality_flags",
]


def empty_deals_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=DEAL_COLUMNS)


def empty_work_orders_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=WORK_ORDER_COLUMNS)
