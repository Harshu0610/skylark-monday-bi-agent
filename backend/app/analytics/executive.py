"""Leadership briefing composition.

The assignment asks the agent to "help prepare data for leadership updates".
Interpreted as: a briefing built for DECISIONS, not for reporting. Each section
answers a question an executive actually has in the room --

    Where do we stand?      snapshot
    What moved?             quarter-on-quarter change
    What should worry us?   ranked risks with figures attached
    What do I say?          talking points, copy-paste ready

Nothing here computes anything new. It composes metrics the deterministic
engine already produced, ranks them by materiality, and drops any line the data
cannot support -- a briefing that quietly omits a risk is worse than no briefing.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..data.quality import build_metric, format_inr
from ..models.schemas import Breakdown, BreakdownRow, MetricResult


def pipeline_created_in_range(
    df: pd.DataFrame, start: date, end: date, label: str
) -> MetricResult:
    """New pipeline created in a window, by deal creation date.

    `created_date` is 99% populated -- the only date field complete enough to
    support a genuine period-over-period comparison. Close dates are not.
    """
    if df.empty:
        return build_metric("pipeline_created", f"Pipeline created ({label})", None, "inr",
                            rows_considered=0, rows_included=0)
    dated = df[df["created_date"].notna()]
    in_range = dated[dated["created_date"].apply(lambda d: start <= d <= end)]
    values = pd.to_numeric(in_range["amount_value"], errors="coerce").dropna()
    undated = len(df) - len(dated)

    return build_metric(
        "pipeline_created", f"Pipeline created ({label})",
        float(values.sum()) if not values.empty else None, "inr",
        formula=f"sum of deal value where created date falls in {label}",
        definition=(
            "New opportunity value entering the funnel in the period, by deal "
            "creation date."
        ),
        rows_considered=len(in_range), rows_included=int(len(values)),
        exclusion_reasons={
            "deal value is blank": len(in_range) - len(values),
            "no created date recorded": undated,
        },
        note=f"{len(in_range)} deals created in {label}.",
    )


def quarter_over_quarter(
    df: pd.DataFrame,
    this_start: date, this_end: date, this_label: str,
    last_start: date, last_end: date, last_label: str,
) -> tuple[MetricResult, MetricResult, MetricResult]:
    """Pipeline created this period vs last, and the movement between them."""
    current = pipeline_created_in_range(df, this_start, this_end, this_label)
    previous = pipeline_created_in_range(df, last_start, last_end, last_label)
    previous.key, previous.label = "pipeline_created_prior", f"Pipeline created ({last_label})"

    if current.value is None or previous.value is None or previous.value == 0:
        change = build_metric(
            "pipeline_change", "Change vs prior quarter", None, "percent",
            definition="Movement in new pipeline created between the two periods.",
            note=(
                "Not comparable: one of the two periods has no deals with recorded "
                "values."
            ),
        )
    else:
        delta = (current.value - previous.value) / previous.value * 100
        change = build_metric(
            "pipeline_change", "Change vs prior quarter", delta, "percent",
            formula=f"({format_inr(current.value)} - {format_inr(previous.value)}) / {format_inr(previous.value)}",
            definition="Movement in new pipeline created between the two periods.",
            rows_considered=current.rows_considered + previous.rows_considered,
            rows_included=current.rows_included + previous.rows_included,
            exclusion_reasons={
                "deal value is blank, so the deal moves the count but not the value":
                    (current.rows_considered - current.rows_included)
                    + (previous.rows_considered - previous.rows_included)
            },
            note=(
                "Based only on deals with recorded values, so it reflects a "
                "direction of travel rather than an exact figure."
            ),
        )
    return current, previous, change


def _pct(part: float | None, whole: float | None) -> float | None:
    if part is None or whole in (None, 0):
        return None
    return part / whole * 100


def rank_risks(
    metrics: dict[str, MetricResult],
    deals: pd.DataFrame,
    work_orders: pd.DataFrame,
    sector_matrix: Breakdown | None,
    accounts_at_risk: Breakdown | None,
) -> list[str]:
    """Risks an executive should act on, ordered by materiality.

    Every line carries its own number. A risk without a figure attached is an
    opinion, and this briefing is not for opinions.
    """
    risks: list[str] = []

    stale = metrics.get("stale_deal_value")
    pipeline = metrics.get("total_open_pipeline")
    if stale and stale.value:
        share = _pct(stale.value, pipeline.value if pipeline else None)
        if share is not None and share >= 99:
            # Every open deal is past its close date. That is a statement about
            # pipeline hygiene, not about any individual deal -- say so, rather
            # than reporting "100% at risk" as if it were a normal risk level.
            risks.append(
                f"Every open deal ({format_inr(stale.value)}) is past its expected "
                "close date. This is a pipeline hygiene problem rather than a "
                "deal-by-deal one: close dates are not being maintained, so the "
                "forecast cannot be time-phased at all."
            )
        else:
            share_txt = f" — {share:.0f}% of open pipeline" if share else ""
            risks.append(
                f"{format_inr(stale.value)} of pipeline sits in deals whose expected "
                f"close date has already passed{share_txt}. The forecast is stale."
            )

    conc = metrics.get("pipeline_concentration")
    if conc and conc.value and conc.value >= 40:
        risks.append(
            f"{conc.value:.0f}% of open pipeline is concentrated in the three "
            "largest deals. Losing one materially changes the quarter."
        )

    if sector_matrix:
        weak = [
            r for r in sector_matrix.rows
            if r.display.get("quadrant") == "Fix delivery"
        ]
        for row in weak[:2]:
            rate = row.values.get("completion_rate")
            delayed = row.values.get("delayed") or 0
            wos = row.values.get("work_orders") or 0
            risks.append(
                f"{row.label}: {row.display.get('pipeline')} of pipeline against a "
                f"{rate:.0f}% delivery completion rate ({int(delayed)} of {int(wos)} "
                "work orders delayed). Selling ahead of the ability to deliver."
            )

    delayed = metrics.get("delayed_work_orders")
    backlog = metrics.get("overdue_backlog_value")
    if delayed and delayed.value:
        value_txt = (
            f", worth {format_inr(backlog.value)}"
            if backlog and backlog.value else ""
        )
        risks.append(
            f"{int(delayed.value)} work orders are past their planned end date"
            f"{value_txt}."
        )

    unbilled = metrics.get("unbilled_completed")
    if unbilled and unbilled.value:
        risks.append(
            f"{int(unbilled.value)} work orders are delivered but not invoiced"
            f"{'. ' + unbilled.note if unbilled.note else '.'} Revenue earned and "
            "not claimed."
        )

    if accounts_at_risk and accounts_at_risk.rows:
        top = accounts_at_risk.rows[0]
        delayed_txt = str(top.display.get("delayed", "")).replace(" delayed", "")
        risks.append(
            f"{top.label} carries {top.display.get('open_pipeline')} of open "
            f"pipeline while running {delayed_txt} delayed work orders — we are "
            "selling into an account we are currently letting down."
        )

    # Data quality is a leadership risk, not a footnote: decisions are being made
    # on these numbers.
    won = metrics.get("won_revenue")
    if won and won.rows_considered and won.rows_included < won.rows_considered:
        missing = won.rows_considered - won.rows_included
        pct = missing / won.rows_considered * 100
        risks.append(
            f"{missing} of {won.rows_considered} won deals ({pct:.0f}%) have no "
            "value recorded. Reported won revenue is a floor, not a figure — "
            "revenue reporting cannot be trusted until this is fixed."
        )

    return risks


def talking_points(
    metrics: dict[str, MetricResult],
    risks: list[str],
    sector_matrix: Breakdown | None,
) -> list[str]:
    """Lines an executive can say out loud in a leadership meeting."""
    points: list[str] = []

    pipeline = metrics.get("total_open_pipeline")
    weighted = metrics.get("weighted_pipeline")
    count = metrics.get("open_deal_count")
    if pipeline and pipeline.value:
        detail = ""
        if count and count.value:
            detail = f" across {int(count.value)} open deals"
        if weighted and weighted.value:
            detail += f"; {format_inr(weighted.value)} probability-weighted"
        points.append(f"Open pipeline is {pipeline.display}{detail}.")

    change = metrics.get("pipeline_change")
    if change and change.value is not None:
        direction = "up" if change.value >= 0 else "down"
        points.append(
            f"New pipeline created is {direction} {abs(change.value):.0f}% on the "
            "prior quarter."
        )

    completion = metrics.get("completion_rate")
    active = metrics.get("active_work_orders")
    if completion and completion.value is not None:
        extra = f", {int(active.value)} projects currently active" if active and active.value else ""
        points.append(f"Delivery completion rate is {completion.display}{extra}.")

    if sector_matrix:
        scale = [r for r in sector_matrix.rows if r.display.get("quadrant") == "Scale"]
        if scale:
            points.append(
                f"{scale[0].label} is our strongest combination of demand and "
                f"delivery ({scale[0].display.get('pipeline')} pipeline at "
                f"{scale[0].display.get('completion_rate')} completion) — the "
                "sector to put more capacity behind."
            )

    if risks:
        points.append(f"Biggest single concern: {risks[0]}")

    win = metrics.get("win_rate")
    if win and win.value is not None:
        points.append(f"Win rate on closed deals is {win.display}.")

    return points


def build_briefing(
    metrics: list[MetricResult],
    breakdowns: list[Breakdown],
    period_label: str,
) -> tuple[list[str], list[str], Breakdown]:
    """Returns (risks, talking_points, briefing_breakdown)."""
    by_key = {m.key: m for m in metrics}
    matrix = next((b for b in breakdowns if b.key == "sector_matrix"), None)
    accounts = next((b for b in breakdowns if b.key == "accounts_at_risk"), None)

    risks = rank_risks(by_key, pd.DataFrame(), pd.DataFrame(), matrix, accounts)
    points = talking_points(by_key, risks, matrix)

    rows = [
        BreakdownRow(key=f"tp{i}", label=point, values={}, display={"point": point})
        for i, point in enumerate(points)
    ]
    briefing = Breakdown(
        key="talking_points",
        title=f"Talking points — {period_label}",
        dimension="point",
        columns=["point"],
        rows=rows,
        chart="table",
        note="Written to be read aloud in a leadership meeting. Every figure is "
             "computed, not estimated.",
    )
    return risks, points, briefing


def period_labels(today: date, fiscal_start_month: int) -> tuple[str, str]:
    """Human labels for the current and prior quarter."""
    from .registry import fiscal_quarter_bounds
    _, _, this_label = fiscal_quarter_bounds(today, 0)
    _, _, last_label = fiscal_quarter_bounds(today, -1)
    return this_label, last_label


def deals_closed_in_range(
    df: pd.DataFrame, start: date, end: date, label: str
) -> MetricResult:
    """Deals won in a window.

    Uses actual close date where present and falls back to expected close date,
    because actual close dates are 92% null. The fallback is flagged rather than
    hidden -- a period figure built partly on expected dates is a weaker claim
    than one built on actuals, and the reader should know which they have.
    """
    if df.empty:
        return build_metric("won_closed", f"Deals won ({label})", None, "count",
                            rows_considered=0, rows_included=0)

    won = df[df["is_won"] == True]  # noqa: E712
    if won.empty:
        return build_metric(
            "won_closed", f"Deals won ({label})", 0, "count",
            rows_considered=len(df), rows_included=0,
            note="No won deals on record.",
        )

    def _closed_on(row):
        return row["actual_close_date"] or row["tentative_close_date"]

    dated = won[won.apply(lambda r: _closed_on(r) is not None, axis=1)]
    in_range = dated[dated.apply(lambda r: start <= _closed_on(r) <= end, axis=1)]
    inferred = int(in_range["actual_close_date"].isna().sum()) if not in_range.empty else 0
    undated = len(won) - len(dated)

    return build_metric(
        "won_closed", f"Deals won ({label})", len(in_range), "count",
        formula=f"count of won deals whose close date falls in {label}",
        definition=(
            "Deals marked Won that closed in the period. Actual close date is "
            "used where recorded; expected close date otherwise."
        ),
        rows_considered=len(won), rows_included=len(dated),
        exclusion_reasons={"no close date of any kind recorded": undated} if undated else {},
        note=(
            f"{inferred} of {len(in_range)} used the expected close date because "
            "no actual close date was recorded." if inferred else None
        ),
    )


def pipeline_created_by_quarter(
    df: pd.DataFrame, today: date, quarters: int = 4
) -> Breakdown:
    """New pipeline created per quarter -- the trend behind the headline delta."""
    from .registry import fiscal_quarter_bounds

    if df.empty:
        return Breakdown(key="created_by_quarter", title="New pipeline by quarter",
                         dimension="quarter", columns=["value", "deals"], rows=[],
                         chart="bar", note="No deals available.")

    rows: list[BreakdownRow] = []
    for offset in range(-(quarters - 1), 1):
        start, end, label = fiscal_quarter_bounds(today, offset)
        metric = pipeline_created_in_range(df, start, end, label)
        rows.append(BreakdownRow(
            key=label, label=label,
            values={"value": metric.value, "deals": metric.rows_considered},
            display={
                "value": format_inr(metric.value),
                "deals": f"{metric.rows_considered}",
            },
        ))
    return Breakdown(
        key="created_by_quarter", title=f"New pipeline created, last {quarters} quarters",
        dimension="quarter", columns=["value", "deals"], rows=rows, chart="bar",
        note=(
            "By deal creation date. Deals with no recorded value contribute to the "
            "deal count but not the value."
        ),
    )


def latest_populated_quarters(
    df: pd.DataFrame, today: date, lookback: int = 8
) -> tuple[tuple[date, date, str], tuple[date, date, str], bool]:
    """The two most recent quarters that actually contain deals.

    "This quarter vs last quarter" is the question people ask, but it is useless
    when the data stops six months ago -- it answers "nothing vs nothing". So we
    walk back to the two most recent quarters with records and report which ones
    we used. Answering a slightly different question and saying so beats
    answering the literal one with two blanks.
    """
    from .registry import fiscal_quarter_bounds

    populated: list[tuple[date, date, str]] = []
    for offset in range(0, -lookback, -1):
        start, end, label = fiscal_quarter_bounds(today, offset)
        if df.empty:
            break
        dated = df[df["created_date"].notna()]
        if not dated.empty and dated["created_date"].apply(
            lambda d: start <= d <= end
        ).any():
            populated.append((start, end, label))
        if len(populated) == 2:
            break

    current, _, _ = fiscal_quarter_bounds(today, 0)
    if len(populated) < 2:
        # Not enough history to compare; hand back the literal quarters and let
        # the metrics report themselves as unavailable.
        return (
            fiscal_quarter_bounds(today, 0),
            fiscal_quarter_bounds(today, -1),
            False,
        )
    shifted = populated[0][0] != current
    return populated[0], populated[1], shifted
