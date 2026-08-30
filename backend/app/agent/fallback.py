"""Deterministic fallbacks for when the LLM is unavailable.

The demo must not die because a model provider rate limited us. These produce a
plainer answer with identical numbers -- which is the whole point of keeping
arithmetic out of the model in the first place.
"""
from __future__ import annotations

import re

from ..models.schemas import (
    AnalysisResult, Board, DatePreset, DateRange, Filters, Intent, QueryPlan,
)

# Ordered most-specific first: the first pattern to match wins.
INTENT_PATTERNS: list[tuple[Intent, list[str]]] = [
    (Intent.DATA_QUALITY, [r"data quality", r"missing data", r"how (good|clean|complete) is the data",
                           r"data problem", r"incomplete"]),
    (Intent.LEADERSHIP_UPDATE, [r"leadership update", r"board update", r"weekly update",
                                r"prepare .*(update|briefing)", r"talking points"]),
    (Intent.PERIOD_COMPARISON, [r"what changed", r"quarter[- ]over[- ]quarter", r"qoq",
                                r"compared to last (quarter|month)", r"vs last quarter",
                                r"trend", r"how has .*(changed|moved)", r"movement",
                                r"growth (over|since)", r"this quarter vs"]),
    (Intent.CROSS_BOARD_ACCOUNT, [r"customers? (who|with|that)", r"accounts? (who|with|that)",
                                  r"both .*(deal|pipeline).*(work|project|delivery)",
                                  r"(sales|pipeline) potential and .*(risk|operational)"]),
    (Intent.CROSS_BOARD_SECTOR, [r"pipeline .*(but|versus|vs).*(execution|delivery)",
                                 r"(strong|strongest).*(pipeline).*(weak|weakest)",
                                 r"winning more .*than .*deliver",
                                 r"compare .*(sales|pipeline).*(execution|delivery|project)",
                                 r"sales (vs|versus) (delivery|operations|execution)"]),
    (Intent.BILLING_RISK, [r"billing", r"unbilled", r"invoice", r"not billed"]),
    (Intent.DELAYED_WORK, [r"delay", r"overdue", r"late", r"behind schedule", r"slipping"]),
    (Intent.DELIVERY_PERFORMANCE, [r"completion rate", r"how long .*project",
                                   r"project duration", r"delivery performance"]),
    (Intent.WORK_ORDER_STATUS, [r"work order", r"projects? (are |is )?(performing|doing|going)",
                                r"how are .*projects", r"operational", r"execution"]),
    (Intent.WIN_RATE, [r"win rate", r"conversion", r"how (often|many) .*(win|won)"]),
    (Intent.WON_REVENUE, [r"won revenue", r"revenue .*won", r"closed won", r"how much .*won"]),
    (Intent.DEAL_RISK, [r"at risk", r"stale", r"worried", r"worry", r"concern",
                        r"risks?\b", r"concentration"]),
    (Intent.FUNNEL, [r"funnel", r"by stage", r"stages"]),
    (Intent.OWNER_PERFORMANCE, [r"salespeople", r"sales ?person", r"by owner", r"owner",
                                r"who (has|is) .*(pipeline|selling)", r"rep\b"]),
    (Intent.SECTOR_BREAKDOWN, [r"which sector", r"sectors?\b.*(strongest|best|highest|compare)",
                               r"by sector", r"sector breakdown"]),
    (Intent.EXECUTIVE_SUMMARY, [r"executive summary", r"ceo", r"overview",
                                r"how.?s the business", r"summary of the business",
                                r"what changed", r"growth opportunit"]),
    (Intent.WEIGHTED_PIPELINE, [r"weighted"]),
    (Intent.PIPELINE, [r"pipeline", r"forecast", r"open deals", r"opportunit"]),
]

SECTOR_HINTS = {
    "mining": "Mining", "renewable": "Renewables", "solar": "Renewables",
    "wind": "Renewables", "energy": "Renewables", "railway": "Railways",
    "rail": "Railways", "powerline": "Powerline", "power line": "Powerline",
    "construction": "Construction", "dsp": "DSP", "tender": "Tender",
    "manufacturing": "Manufacturing", "aviation": "Aviation",
    "security": "Security and Surveillance",
}


def keyword_plan(question: str) -> QueryPlan:
    """Classify a question without an LLM. Coarse, but it never fails."""
    q = question.lower()

    intent = Intent.EXECUTIVE_SUMMARY
    for candidate, patterns in INTENT_PATTERNS:
        if any(re.search(p, q) for p in patterns):
            intent = candidate
            break

    filters = Filters()
    assumptions: list[str] = []

    for hint, sector in SECTOR_HINTS.items():
        if hint in q:
            filters.sector = sector
            if hint == "energy":
                assumptions.append(
                    "There is no 'Energy' sector in the data. Interpreted as Renewables; "
                    "Powerline may also be relevant."
                )
            break

    if "this quarter" in q or "current quarter" in q:
        filters.date_range = DateRange(preset=DatePreset.THIS_QUARTER)
    elif "last quarter" in q:
        filters.date_range = DateRange(preset=DatePreset.LAST_QUARTER)
    elif "this month" in q:
        filters.date_range = DateRange(preset=DatePreset.THIS_MONTH)
    elif "this year" in q:
        filters.date_range = DateRange(preset=DatePreset.THIS_YEAR)

    if intent == Intent.PERIOD_COMPARISON:
        boards = [Board.DEALS]
    elif intent in (Intent.CROSS_BOARD_SECTOR, Intent.CROSS_BOARD_ACCOUNT,
                    Intent.EXECUTIVE_SUMMARY, Intent.LEADERSHIP_UPDATE,
                    Intent.DATA_QUALITY):
        boards = [Board.DEALS, Board.WORK_ORDERS]
    elif intent in (Intent.WORK_ORDER_STATUS, Intent.DELIVERY_PERFORMANCE,
                    Intent.DELAYED_WORK, Intent.BILLING_RISK):
        boards = [Board.WORK_ORDERS]
    else:
        boards = [Board.DEALS]

    return QueryPlan(
        intent=intent, boards=boards, filters=filters, assumptions=assumptions,
        confidence_in_interpretation="medium",
    )


def template_narrative(result: AnalysisResult) -> dict:
    """Render a result without an LLM. Numbers identical, prose plainer."""
    if result.unsupported:
        return {"answer": result.unsupported, "insight": None, "risks": [], "follow_ups": []}

    named = [m for m in result.metrics if m.value is not None]
    unavailable = [m for m in result.metrics if m.value is None]

    if named:
        head = named[0]
        answer = f"{head.label} is {head.display}."
        if len(named) > 1:
            rest = ", ".join(f"{m.label.lower()} {m.display}" for m in named[1:4])
            answer += f" Alongside that: {rest}."
    else:
        answer = (
            "I could not compute a figure for that question -- the records in scope "
            "do not carry the values it needs."
        )

    risks: list[str] = list(result.caveats)
    for metric in result.metrics:
        if metric.note:
            risks.append(metric.note)
    for metric in unavailable:
        risks.append(f"{metric.label} could not be calculated from the available data.")
    if result.ledger.confidence != "high":
        risks.append(
            f"Confidence is {result.ledger.confidence}: "
            f"{result.ledger.rows_included} of {result.ledger.rows_considered} "
            "records in scope had the fields this answer needs."
        )
    risks.extend(result.ledger.warnings)

    return {
        "answer": answer,
        "insight": None,
        "risks": risks[:6],
        "follow_ups": [],
    }
