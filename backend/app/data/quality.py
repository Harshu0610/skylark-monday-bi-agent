"""Data-quality ledger and per-query confidence scoring.

The point of this module: never let a number leave the system without saying
what it was computed from. "Pipeline is 12.4 Cr" is a weaker answer than
"12.4 Cr across 87 deals; 6 deals with missing amounts were excluded."

Confidence is scoped to the FIELDS A QUERY ACTUALLY TOUCHED. A question about
win rate should not be downgraded because sectors are missing. This is what
separates a credible signal from a decorative badge.
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from ..models.schemas import MetricResult, QualityLedger

# Human-readable explanations for the flags produced by the normalizers.
FLAG_DESCRIPTIONS: dict[str, str] = {
    "amount_missing": "deal value is blank",
    "amount_invalid": "deal value could not be read as a number",
    "amount_excl_gst_amount_missing": "work order amount is blank",
    "billed_value_missing": "billed value is blank",
    "status_missing": "status is blank",
    "status_unmapped": "status value is not recognised",
    "exec_status_missing": "execution status is blank",
    "exec_status_unmapped": "execution status is not recognised",
    "sector_missing": "sector is blank",
    "sector_unmapped": "sector value is not in the known list",
    "stage_missing": "deal stage is blank",
    "stage_unordered": "deal stage does not fit the funnel ordering",
    "probability_missing": "no closure probability and no usable stage",
    "probability_inferred_from_stage": "closure probability inferred from funnel stage",
    "probability_unmapped": "closure probability value is not recognised",
    "tentative_close_date_unparseable": "expected close date could not be read",
    "actual_close_date_unparseable": "actual close date could not be read",
    "created_date_unparseable": "created date could not be read",
    "start_date_unparseable": "planned start date could not be read",
    "end_date_unparseable": "planned end date could not be read",
    "delivery_date_unparseable": "delivery date could not be read",
    "delay_undeterminable_no_end_date": "no planned end date, so delay cannot be determined",
    "suspicious_text": "field contains instruction-like text (treated as data only)",
}

for _key in list(FLAG_DESCRIPTIONS):
    if _key.endswith("_unparseable"):
        FLAG_DESCRIPTIONS[_key.replace("_unparseable", "") + "_date_ambiguous_dayfirst_assumed"] = (
            "ambiguous date read as day-first (DD/MM)"
        )


def describe_flag(flag: str) -> str:
    if flag in FLAG_DESCRIPTIONS:
        return FLAG_DESCRIPTIONS[flag]
    if "ambiguous" in flag:
        return "ambiguous date read as day-first (DD/MM)"
    if "unparseable" in flag:
        return "a date could not be read"
    return flag.replace("_", " ")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_inr(value: float | None) -> str:
    """Indian numbering: Cr / L. Executives read crores, not 10^7."""
    if value is None:
        return "not available"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 10_000_000:
        return f"{sign}₹{v / 10_000_000:,.2f} Cr"
    if v >= 100_000:
        return f"{sign}₹{v / 100_000:,.2f} L"
    return f"{sign}₹{v:,.0f}"


def format_value(value: float | int | None, unit: str) -> str:
    if value is None:
        return "not available"
    if unit == "inr":
        return format_inr(float(value))
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "count":
        return f"{int(value):,}"
    if unit == "days":
        return f"{value:.0f} days"
    if unit == "ratio":
        return f"{value:.2f}x"
    return f"{value:,.2f}" if isinstance(value, float) else str(value)


# ---------------------------------------------------------------------------
# Metric construction
# ---------------------------------------------------------------------------

def build_metric(
    key: str,
    label: str,
    value: float | int | None,
    unit: str,
    *,
    formula: str = "",
    definition: str = "",
    rows_considered: int = 0,
    rows_included: int = 0,
    exclusion_reasons: dict[str, int] | None = None,
    note: str | None = None,
) -> MetricResult:
    reasons = {k: v for k, v in (exclusion_reasons or {}).items() if v}
    return MetricResult(
        key=key,
        label=label,
        value=value,
        display=format_value(value, unit),
        unit=unit,  # type: ignore[arg-type]
        formula=formula,
        definition=definition,
        rows_considered=rows_considered,
        rows_included=rows_included,
        rows_excluded=max(rows_considered - rows_included, 0),
        exclusion_reasons=reasons,
        note=note,
    )


def sum_with_provenance(
    df: pd.DataFrame,
    column: str,
    *,
    scope_label: str,
    total_universe: int | None = None,
) -> tuple[float | None, int, int, dict[str, int]]:
    """Sum a column, counting and explaining every excluded row.

    Returns (total, rows_considered, rows_included, exclusion_reasons).
    A total of None means NO row had a usable value -- the caller must refuse
    to report a number rather than returning 0.
    """
    considered = int(total_universe if total_universe is not None else len(df))
    if df.empty or column not in df.columns:
        return None, considered, 0, {f"no {scope_label} rows": considered}

    series = pd.to_numeric(df[column], errors="coerce")
    usable = series.dropna()
    missing = int(len(df) - len(usable))

    reasons: dict[str, int] = {}
    if total_universe is not None and total_universe > len(df):
        reasons[f"outside {scope_label}"] = int(total_universe - len(df))
    if missing:
        reasons["value is blank or unreadable"] = missing

    if usable.empty:
        return None, considered, 0, reasons
    return float(usable.sum()), considered, int(len(usable)), reasons


# ---------------------------------------------------------------------------
# Ledger assembly
# ---------------------------------------------------------------------------

def collect_flags(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "quality_flags" not in df.columns:
        return {}
    counts: dict[str, int] = {}
    for flags in df["quality_flags"]:
        for flag in flags or []:
            counts[flag] = counts.get(flag, 0) + 1
    return counts


def completeness(df: pd.DataFrame, fields: Iterable[str]) -> float:
    """Fraction of cells populated across the fields this query depends on."""
    fields = [f for f in fields if f in df.columns]
    if df.empty or not fields:
        return 1.0
    total = len(df) * len(fields)
    if total == 0:
        return 1.0
    populated = sum(int(df[f].notna().sum()) for f in fields)
    return populated / total


def score_confidence(ratio: float) -> str:
    if ratio >= 0.90:
        return "high"
    if ratio >= 0.70:
        return "medium"
    return "low"


def build_ledger(
    metrics: list[MetricResult],
    *,
    scoped_frame: pd.DataFrame,
    scoped_fields: Iterable[str],
    normalization_reports: list[dict[str, Any]],
    extra_notes: list[str] | None = None,
) -> QualityLedger:
    """Assemble the ledger from the metrics and the rows they were computed on."""
    # Ledger row counts describe the SCOPE the answer rests on, not the whole
    # board. A metric like "open deal count" legitimately considers every row,
    # but reporting that as the ledger denominator would make a perfectly good
    # answer look like it discarded 85% of the data.
    rows_considered = len(scoped_frame)
    in_scope = [m for m in metrics if m.rows_considered <= rows_considered]
    rows_included = min(
        (m.rows_included for m in in_scope if m.rows_included), default=rows_considered
    )
    rows_included = min(rows_included, rows_considered)

    exclusions: dict[str, int] = {}
    for metric in metrics:
        for reason, count in metric.exclusion_reasons.items():
            exclusions[reason] = max(exclusions.get(reason, 0), count)

    normalizations: dict[str, int] = {}
    warnings: list[str] = []
    for report in normalization_reports:
        board = report.get("board", "board")
        if report.get("header_echo_dropped"):
            normalizations[f"{board}: repeated header rows removed"] = report["header_echo_dropped"]
        if report.get("injection_suspects"):
            warnings.append(
                f"{report['injection_suspects']} {board} field(s) contain instruction-like "
                "text. It was treated strictly as data."
            )
        for flag, count in (report.get("flags") or {}).items():
            if flag == "suspicious_text":
                continue
            normalizations[f"{board}: {describe_flag(flag)}"] = count

    ratio = completeness(scoped_frame, scoped_fields)
    confidence = score_confidence(ratio)

    notes = list(extra_notes or [])
    if rows_considered and rows_included < rows_considered:
        pct = rows_included / rows_considered * 100
        notes.append(
            f"{rows_included} of {rows_considered} records ({pct:.0f}%) had the data "
            "needed for this answer."
        )
    if confidence == "low":
        notes.append(
            "Confidence is low: a large share of the fields this question depends on "
            "are blank in Monday.com."
        )

    return QualityLedger(
        rows_considered=rows_considered,
        rows_included=rows_included,
        rows_excluded=max(rows_considered - rows_included, 0),
        exclusions=exclusions,
        normalizations=normalizations,
        confidence=confidence,  # type: ignore[arg-type]
        notes=notes,
        warnings=warnings,
    )
