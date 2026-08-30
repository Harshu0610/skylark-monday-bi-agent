"""Deterministic deal metrics.

Every function here returns a MetricResult carrying its own provenance. No
function ever substitutes 0 for a missing value, and any metric whose inputs
are entirely unusable returns value=None so the caller can refuse to answer
rather than inventing a number.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..data.quality import build_metric, format_inr, sum_with_provenance
from ..models.schemas import Breakdown, BreakdownRow, MetricResult


def _open(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["is_open"] == True] if not df.empty else df  # noqa: E712


def _won(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["is_won"] == True] if not df.empty else df  # noqa: E712


def _lost(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["is_lost"] == True] if not df.empty else df  # noqa: E712


# ---------------------------------------------------------------------------
# Headline value metrics
# ---------------------------------------------------------------------------

def total_open_pipeline(df: pd.DataFrame) -> MetricResult:
    scope = _open(df)
    total, considered, included, reasons = sum_with_provenance(
        scope, "amount_value", scope_label="open deals", total_universe=len(scope)
    )
    return build_metric(
        "total_open_pipeline",
        "Open pipeline",
        total,
        "inr",
        formula="sum of deal value where Deal Status = Open",
        definition=(
            "Total value of deals still live in the funnel. Excludes Won, Lost "
            "and On Hold deals, and any deal with no recorded value."
        ),
        rows_considered=considered,
        rows_included=included,
        exclusion_reasons=reasons,
    )


def weighted_pipeline(df: pd.DataFrame) -> MetricResult:
    scope = _open(df).copy()
    considered = len(scope)
    if scope.empty:
        return build_metric(
            "weighted_pipeline", "Weighted pipeline", None, "inr",
            rows_considered=considered, rows_included=0,
            exclusion_reasons={"no open deals": considered},
        )

    scope["_amt"] = pd.to_numeric(scope["amount_value"], errors="coerce")
    scope["_w"] = pd.to_numeric(scope["probability_weight"], errors="coerce")
    usable = scope.dropna(subset=["_amt", "_w"])

    reasons: dict[str, int] = {}
    missing_amt = int(scope["_amt"].isna().sum())
    missing_w = int(scope["_amt"].notna().sum() - usable.shape[0])
    if missing_amt:
        reasons["deal value is blank"] = missing_amt
    if missing_w:
        reasons["no closure probability and no usable stage"] = missing_w

    total = float((usable["_amt"] * usable["_w"]).sum()) if not usable.empty else None
    inferred = int(
        usable["quality_flags"].apply(
            lambda f: "probability_inferred_from_stage" in (f or [])
        ).sum()
    ) if "quality_flags" in usable.columns else 0

    note = None
    if inferred:
        note = (
            f"{inferred} of {len(usable)} deals had no Closure Probability; their "
            "weight was inferred from funnel stage."
        )

    return build_metric(
        "weighted_pipeline",
        "Weighted pipeline",
        total,
        "inr",
        formula="sum of (deal value x closure probability) for open deals",
        definition=(
            "Pipeline discounted by likelihood of closing. High=0.75, "
            "Medium=0.45, Low=0.20; where blank, inferred from funnel stage."
        ),
        rows_considered=considered,
        rows_included=len(usable),
        exclusion_reasons=reasons,
        note=note,
    )


def won_revenue(df: pd.DataFrame) -> MetricResult:
    scope = _won(df)
    total, considered, included, reasons = sum_with_provenance(
        scope, "amount_value", scope_label="won deals", total_universe=len(scope)
    )
    note = None
    if len(scope) and included < len(scope):
        missing_pct = (len(scope) - included) / len(scope) * 100
        note = (
            f"{len(scope) - included} of {len(scope)} won deals ({missing_pct:.0f}%) "
            "have no value recorded, so true won revenue is higher than this figure."
        )
    return build_metric(
        "won_revenue",
        "Won revenue",
        total,
        "inr",
        formula="sum of deal value where Deal Status = Won",
        definition="Recorded value of closed-won deals.",
        rows_considered=considered,
        rows_included=included,
        exclusion_reasons=reasons,
        note=note,
    )


def lost_value(df: pd.DataFrame) -> MetricResult:
    scope = _lost(df)
    total, considered, included, reasons = sum_with_provenance(
        scope, "amount_value", scope_label="lost deals", total_universe=len(scope)
    )
    return build_metric(
        "lost_value", "Lost deal value", total, "inr",
        formula="sum of deal value where Deal Status = Lost/Dead",
        definition="Recorded value of deals that were lost or went dead.",
        rows_considered=considered, rows_included=included, exclusion_reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Rates and sizes
# ---------------------------------------------------------------------------

def win_rate(df: pd.DataFrame) -> MetricResult:
    """Won / (Won + Lost), by deal COUNT.

    Counted on closed deals only -- including open deals in the denominator
    would make the rate drift down purely because the pipeline is growing.
    Counted by number of deals rather than value, because 52% of values are
    missing and a value-weighted rate would be badly biased.
    """
    won = int((df["is_won"] == True).sum()) if not df.empty else 0  # noqa: E712
    lost = int((df["is_lost"] == True).sum()) if not df.empty else 0  # noqa: E712
    closed = won + lost

    if closed == 0:
        return build_metric(
            "win_rate", "Win rate", None, "percent",
            formula="won deals / (won + lost) deals",
            definition="Share of closed deals that were won.",
            rows_considered=len(df), rows_included=0,
            exclusion_reasons={"no closed deals in scope": len(df)},
            note="No closed deals in this scope, so a win rate cannot be calculated.",
        )

    return build_metric(
        "win_rate", "Win rate", won / closed * 100, "percent",
        formula=f"{won} won / {closed} closed deals",
        definition=(
            "Share of CLOSED deals that were won, by deal count. Open deals are "
            "excluded from the denominator."
        ),
        rows_considered=len(df), rows_included=closed,
        exclusion_reasons={"deal is still open or on hold": len(df) - closed},
    )


def _size_metric(df: pd.DataFrame, key: str, label: str, how: str) -> MetricResult:
    scope = _open(df)
    values = pd.to_numeric(scope["amount_value"], errors="coerce").dropna() if not scope.empty else pd.Series(dtype=float)
    if values.empty:
        return build_metric(
            key, label, None, "inr",
            rows_considered=len(scope), rows_included=0,
            exclusion_reasons={"no open deal has a recorded value": len(scope)},
        )
    value = float(values.median() if how == "median" else values.mean())
    return build_metric(
        key, label, value, "inr",
        formula=f"{how} of deal value across open deals with a recorded value",
        definition=(
            "Median is reported alongside the mean because deal values here are "
            "heavily skewed by a few very large deals."
        ),
        rows_considered=len(scope), rows_included=int(len(values)),
        exclusion_reasons={"deal value is blank": len(scope) - len(values)},
    )


def median_deal_size(df: pd.DataFrame) -> MetricResult:
    return _size_metric(df, "median_deal_size", "Median deal size", "median")


def average_deal_size(df: pd.DataFrame) -> MetricResult:
    return _size_metric(df, "average_deal_size", "Average deal size", "mean")


def open_deal_count(df: pd.DataFrame) -> MetricResult:
    scope = _open(df)
    return build_metric(
        "open_deal_count", "Open deals", len(scope), "count",
        formula="count of deals where Deal Status = Open",
        definition="Number of live opportunities.",
        # Classifying a deal as not-open is not an exclusion; the count is exact.
        rows_considered=len(df), rows_included=len(df),
    )


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

def stale_deals(df: pd.DataFrame) -> MetricResult:
    """Open deals whose expected close date has already passed."""
    if df.empty:
        return build_metric("stale_deals", "Stale open deals", 0, "count",
                            rows_considered=0, rows_included=0)
    scope = _open(df)
    stale = scope[scope["is_stale"] == True]  # noqa: E712
    undated = int(scope["tentative_close_date"].isna().sum())
    return build_metric(
        "stale_deals", "Stale open deals", len(stale), "count",
        formula="open deals where expected close date < today",
        definition=(
            "Deals still marked Open whose expected close date has already "
            "passed -- the forecast is out of date or the deal has slipped."
        ),
        rows_considered=len(scope), rows_included=len(scope) - undated,  # undated genuinely cannot be judged
        exclusion_reasons={"no expected close date recorded": undated},
        note=(
            f"{undated} open deals have no expected close date and could not be "
            "assessed." if undated else None
        ),
    )


def stale_deal_value(df: pd.DataFrame) -> MetricResult:
    scope = _open(df)
    stale = scope[scope["is_stale"] == True] if not scope.empty else scope  # noqa: E712
    total, considered, included, reasons = sum_with_provenance(
        stale, "amount_value", scope_label="stale open deals", total_universe=len(scope)
    )
    return build_metric(
        "stale_deal_value", "Value at risk (stale deals)", total, "inr",
        formula="sum of deal value for open deals past their expected close date",
        definition="Pipeline value tied up in deals whose close date has slipped.",
        rows_considered=considered, rows_included=included, exclusion_reasons=reasons,
    )


def pipeline_concentration(df: pd.DataFrame, top_n: int = 3) -> MetricResult:
    """Share of open pipeline held by the largest N deals.

    Concentration is the risk an executive most often cannot see from a total.
    """
    scope = _open(df)
    values = pd.to_numeric(scope["amount_value"], errors="coerce").dropna() if not scope.empty else pd.Series(dtype=float)
    if len(values) < 2:
        return build_metric(
            "pipeline_concentration", f"Top {top_n} deal concentration", None, "percent",
            rows_considered=len(scope), rows_included=int(len(values)),
            exclusion_reasons={"too few valued deals to assess concentration": len(scope)},
        )
    total = float(values.sum())
    top = float(values.nlargest(top_n).sum())
    return build_metric(
        "pipeline_concentration", f"Top {top_n} deal concentration",
        (top / total * 100) if total else None, "percent",
        formula=f"value of {top_n} largest open deals / total open pipeline",
        definition=(
            f"How much of the open pipeline sits in just {top_n} deals. High "
            "concentration means the forecast depends on a few outcomes."
        ),
        rows_considered=len(scope), rows_included=int(len(values)),
        exclusion_reasons={"deal value is blank": len(scope) - len(values)},
        note=f"Largest {top_n} deals total {format_inr(top)}.",
    )


def average_pipeline_age(df: pd.DataFrame) -> MetricResult:
    scope = _open(df)
    ages = pd.to_numeric(scope["age_days"], errors="coerce").dropna() if not scope.empty else pd.Series(dtype=float)
    if ages.empty:
        return build_metric(
            "average_pipeline_age", "Average age of open deals", None, "days",
            rows_considered=len(scope), rows_included=0,
            exclusion_reasons={"no created date recorded": len(scope)},
        )
    return build_metric(
        "average_pipeline_age", "Average age of open deals", float(ages.mean()), "days",
        formula="mean of (today - created date) across open deals",
        definition="How long live deals have been sitting in the funnel.",
        rows_considered=len(scope), rows_included=int(len(ages)),
        exclusion_reasons={"no created date recorded": len(scope) - len(ages)},
    )


def deals_closing_in_range(
    df: pd.DataFrame, start: date, end: date, label: str = "the period"
) -> MetricResult:
    scope = _open(df)
    if scope.empty:
        return build_metric(
            "deals_closing", f"Pipeline closing in {label}", None, "inr",
            rows_considered=len(df), rows_included=0,
            exclusion_reasons={"no open deals": len(df)},
        )
    dated = scope[scope["tentative_close_date"].notna()]
    in_range = dated[
        dated["tentative_close_date"].apply(lambda d: start <= d <= end)
    ]
    total, considered, included, reasons = sum_with_provenance(
        in_range, "amount_value", scope_label=label, total_universe=len(scope)
    )
    undated = len(scope) - len(dated)
    if undated:
        reasons["no expected close date recorded"] = undated
    return build_metric(
        "deals_closing", f"Pipeline closing in {label}", total, "inr",
        formula=f"sum of open deal value where expected close date is within {label}",
        definition="Open pipeline forecast to close inside the requested window.",
        rows_considered=considered, rows_included=included, exclusion_reasons=reasons,
        note=(
            f"{undated} open deals have no expected close date and are not counted "
            "in this forecast." if undated else None
        ),
    )


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------

def _group_breakdown(
    df: pd.DataFrame,
    column: str,
    key: str,
    title: str,
    dimension: str,
    *,
    chart: str = "bar",
    open_only: bool = True,
) -> Breakdown:
    scope = _open(df) if open_only else df
    if scope.empty or column not in scope.columns:
        return Breakdown(key=key, title=title, dimension=dimension,
                         columns=["Deals", "Value"], rows=[], chart=chart,  # type: ignore[arg-type]
                         note="No records available for this breakdown.")

    working = scope.copy()
    working[column] = working[column].fillna("Not specified")
    working["_amt"] = pd.to_numeric(working["amount_value"], errors="coerce")

    grouped = working.groupby(column, dropna=False).agg(
        deals=("_amt", "size"),
        valued=("_amt", "count"),
        value=("_amt", "sum"),
    ).reset_index()
    grouped = grouped.sort_values("value", ascending=False)

    rows: list[BreakdownRow] = []
    for _, r in grouped.iterrows():
        missing = int(r["deals"] - r["valued"])
        value = float(r["value"]) if r["valued"] else None
        rows.append(
            BreakdownRow(
                key=str(r[column]),
                label=str(r[column]),
                values={
                    "deals": int(r["deals"]),
                    "value": value,
                    "deals_missing_value": missing,
                },
                display={
                    "deals": f"{int(r['deals']):,}",
                    "value": format_inr(value),
                    "deals_missing_value": str(missing),
                },
            )
        )

    total_missing = int(sum(r.values["deals_missing_value"] or 0 for r in rows))
    note = (
        f"{total_missing} deals have no recorded value and contribute to the deal "
        "counts but not the value totals." if total_missing else None
    )
    return Breakdown(
        key=key, title=title, dimension=dimension,
        columns=["deals", "value", "deals_missing_value"],
        rows=rows, chart=chart, note=note,  # type: ignore[arg-type]
    )


def pipeline_by_sector(df: pd.DataFrame) -> Breakdown:
    return _group_breakdown(df, "sector_norm", "pipeline_by_sector",
                            "Open pipeline by sector", "sector")


def pipeline_by_owner(df: pd.DataFrame) -> Breakdown:
    return _group_breakdown(df, "owner_code", "pipeline_by_owner",
                            "Open pipeline by owner", "owner")


def pipeline_by_stage(df: pd.DataFrame) -> Breakdown:
    """Funnel view, ordered by the lettered stage prefix rather than by value."""
    scope = _open(df)
    if scope.empty:
        return Breakdown(key="funnel", title="Pipeline funnel", dimension="stage",
                         columns=["deals", "value"], rows=[], chart="funnel",
                         note="No open deals available.")
    working = scope.copy()
    working["stage_norm"] = working["stage_norm"].fillna("Not specified")
    working["_amt"] = pd.to_numeric(working["amount_value"], errors="coerce")
    grouped = working.groupby(["stage_norm", "stage_order"], dropna=False).agg(
        deals=("_amt", "size"), valued=("_amt", "count"), value=("_amt", "sum"),
    ).reset_index().sort_values("stage_order", na_position="last")

    rows = [
        BreakdownRow(
            key=str(r["stage_norm"]), label=str(r["stage_norm"]),
            values={"deals": int(r["deals"]),
                    "value": float(r["value"]) if r["valued"] else None},
            display={"deals": f"{int(r['deals']):,}",
                     "value": format_inr(float(r["value"]) if r["valued"] else None)},
        )
        for _, r in grouped.iterrows()
    ]
    return Breakdown(key="funnel", title="Pipeline funnel by stage", dimension="stage",
                     columns=["deals", "value"], rows=rows, chart="funnel")


def top_deals(df: pd.DataFrame, limit: int = 5) -> Breakdown:
    scope = _open(df)
    if scope.empty:
        return Breakdown(key="top_deals", title="Largest open deals", dimension="deal",
                         columns=["value", "stage", "sector"], rows=[], chart="table")
    working = scope.copy()
    working["_amt"] = pd.to_numeric(working["amount_value"], errors="coerce")
    working = working.dropna(subset=["_amt"]).nlargest(limit, "_amt")
    rows = [
        BreakdownRow(
            key=str(r["deal_name_raw"] or "Unnamed"),
            label=str(r["deal_name_raw"] or "Unnamed"),
            values={"value": float(r["_amt"])},
            display={
                "value": format_inr(float(r["_amt"])),
                "stage": str(r["stage_norm"] or "-"),
                "sector": str(r["sector_norm"] or "-"),
            },
        )
        for _, r in working.iterrows()
    ]
    return Breakdown(key="top_deals", title=f"Largest {len(rows)} open deals",
                     dimension="deal", columns=["value", "stage", "sector"],
                     rows=rows, chart="table")
