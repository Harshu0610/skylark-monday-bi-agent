"""Golden-question evaluation suite.

Runs the real pipeline -- normalization, routing, analytics, ledger -- over the
actual Skylark spreadsheets and asserts what each question should produce.

Two deliberate choices:

  * It reads the local CSVs rather than Monday.com, so it runs in CI with no
    secrets and gives the same answer every time. The code path is the real one;
    only the transport differs.

  * It asserts INTENT and METRIC VALUES, never prose. Prose is the model's job
    and varies; intent and arithmetic are ours and must not.

    pytest -m eval          run just this suite
    pytest -m "not eval"    skip it

If the source spreadsheets change, these numbers change. That is the point:
this suite is a tripwire on the analytics layer, and a failure here means
either the data moved or a metric regressed.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.agent import fallback
from app.analytics.registry import run_analysis
from app.data.pipeline import normalize_deals, normalize_work_orders
from app.models.schemas import Board, Intent, QueryPlan

pytestmark = pytest.mark.eval

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data_clean"

# Pinned so quarter arithmetic is stable regardless of when the suite runs.
TODAY = date(2026, 8, 30)


@pytest.fixture(scope="module")
def board_data():
    from app.agent.local_source import DEALS_MAP, WORK_ORDERS_MAP

    deals_csv = DATA / "deals_clean.csv"
    wo_csv = DATA / "work_orders_clean.csv"
    if not deals_csv.exists() or not wo_csv.exists():
        pytest.skip("run scripts/prepare_for_monday.py first")

    d_raw = pd.read_csv(deals_csv).rename(columns=DEALS_MAP)
    w_raw = pd.read_csv(wo_csv).rename(columns=WORK_ORDERS_MAP)
    deals, d_rep = normalize_deals(d_raw, today=TODAY)
    work_orders, w_rep = normalize_work_orders(w_raw, today=TODAY)
    return deals, work_orders, [d_rep.as_dict(), w_rep.as_dict()]


def answer(board_data, question: str):
    """Route a question and run it, exactly as the API does."""
    deals, work_orders, reports = board_data
    plan = fallback.keyword_plan(question)
    result = run_analysis(plan, deals, work_orders, reports, today=TODAY)
    return plan, result, {m.key: m for m in result.metrics}


# ---------------------------------------------------------------------------
# Routing: does each founder question reach the right analysis?
# ---------------------------------------------------------------------------

GOLDEN_ROUTING = [
    ("What's our total pipeline?", Intent.PIPELINE),
    ("What's our weighted pipeline this quarter?", Intent.WEIGHTED_PIPELINE),
    ("How much revenue have we won?", Intent.WON_REVENUE),
    ("What's our win rate?", Intent.WIN_RATE),
    ("Which deals are at risk?", Intent.DEAL_RISK),
    ("Which sector has the strongest pipeline?", Intent.SECTOR_BREAKDOWN),
    ("Which salespeople have the highest pipeline?", Intent.OWNER_PERFORMANCE),
    ("How are our current projects performing?", Intent.WORK_ORDER_STATUS),
    ("How many work orders are delayed?", Intent.DELAYED_WORK),
    ("How much work is delivered but unbilled?", Intent.BILLING_RISK),
    ("Which sectors have the strongest pipeline but weak execution?",
     Intent.CROSS_BOARD_SECTOR),
    ("Which customers have both high sales potential and operational risk?",
     Intent.CROSS_BOARD_ACCOUNT),
    ("What changed this quarter?", Intent.PERIOD_COMPARISON),
    ("Give me a CEO-level summary of the business.", Intent.EXECUTIVE_SUMMARY),
    ("What data quality problems do we have?", Intent.DATA_QUALITY),
    ("Prepare this week's leadership update.", Intent.LEADERSHIP_UPDATE),
]


@pytest.mark.parametrize("question,expected", GOLDEN_ROUTING)
def test_question_routes_to_expected_analysis(question, expected):
    assert fallback.keyword_plan(question).intent == expected


@pytest.mark.parametrize("question,expected", GOLDEN_ROUTING)
def test_every_golden_question_produces_an_answer(board_data, question, expected):
    plan, result, metrics = answer(board_data, question)
    assert result.unsupported is None
    assert result.metrics or result.breakdowns, f"no output for: {question}"


# ---------------------------------------------------------------------------
# Values: pinned against the real spreadsheets
# ---------------------------------------------------------------------------

def test_dataset_shape(board_data):
    deals, work_orders, reports = board_data
    assert len(deals) == 344
    assert len(work_orders) == 176


def test_header_echo_rows_are_caught_in_the_raw_source():
    """The cleaned CSVs already have them removed, so this asserts against the
    original spreadsheet -- which is what Monday.com actually holds."""
    xlsx = ROOT / "Deal funnel Data.xlsx"
    if not xlsx.exists():
        pytest.skip("source spreadsheet not present")
    from app.agent.local_source import DEALS_MAP
    raw = pd.read_excel(xlsx).rename(columns=DEALS_MAP)
    _, report = normalize_deals(raw, today=TODAY)
    assert report.header_echo_dropped == 2
    assert report.rows_in == 346 and report.rows_out == 344


def test_total_pipeline(board_data):
    _, result, m = answer(board_data, "What's our total pipeline?")
    assert m["total_open_pipeline"].value == pytest.approx(688_152_293, rel=1e-4)
    assert m["open_deal_count"].value == 49
    assert m["total_open_pipeline"].rows_included == 47   # two blanks excluded
    assert result.ledger.confidence == "high"


def test_won_revenue_is_low_confidence_and_says_why(board_data):
    """The headline honesty case: 61% of won deals carry no value."""
    _, result, m = answer(board_data, "How much revenue have we won?")
    won = m["won_revenue"]
    assert won.value == pytest.approx(95_038_939, rel=1e-4)
    assert won.rows_considered == 165
    assert won.rows_included == 64
    assert result.ledger.confidence == "low"
    assert "no value recorded" in (won.note or "")


def test_win_rate(board_data):
    _, _, m = answer(board_data, "What's our win rate?")
    assert m["win_rate"].value == pytest.approx(56.51, abs=0.05)


def test_delayed_work_orders(board_data):
    _, _, m = answer(board_data, "How many work orders are delayed?")
    assert m["delayed_work_orders"].value == 42
    assert m["completion_rate"].value == pytest.approx(75.0, abs=0.1)
    # Rows with no planned end date are excluded, never assumed on-time.
    assert m["delayed_work_orders"].rows_included < 176


def test_railways_is_the_execution_problem(board_data):
    """The cross-board finding the whole demo rests on."""
    _, result, _ = answer(
        board_data, "Which sectors have the strongest pipeline but weak execution?"
    )
    matrix = next(b for b in result.breakdowns if b.key == "sector_matrix")
    rail = next(r for r in matrix.rows if r.label == "Railways")
    assert rail.values["completion_rate"] == pytest.approx(15.4, abs=0.5)
    assert rail.values["delayed"] == 11
    assert rail.display["quadrant"] == "Fix delivery"

    mining = next(r for r in matrix.rows if r.label == "Mining")
    assert mining.values["completion_rate"] > 80
    assert mining.display["quadrant"] == "Scale"


def test_cross_board_coverage_is_reported(board_data):
    _, _, m = answer(
        board_data, "Which customers have both high sales potential and operational risk?"
    )
    coverage = m["account_link_coverage"]
    assert coverage.value == pytest.approx(89.7, abs=1.0)
    assert coverage.exclusion_reasons["work-order account has no matching deal"] == 6


def test_period_movement_falls_back_to_populated_quarters(board_data):
    """The data ends in Q4 FY26, so a literal 'this quarter' comparison is empty.
    The agent must compare the most recent quarters that have records, and say so."""
    _, result, m = answer(board_data, "What changed this quarter?")
    assert m["pipeline_change"].value is not None
    assert any("most recent quarters that contain records" in c for c in result.caveats)


def test_sectors_are_normalized_to_the_known_set(board_data):
    deals, _, _ = board_data
    sectors = set(deals["sector_norm"].dropna().unique())
    assert "Sector/service" not in sectors      # header echo would create this
    assert {"Mining", "Renewables", "Railways", "Powerline"} <= sectors
    assert "Energy" not in sectors              # the sector everyone assumes exists


# ---------------------------------------------------------------------------
# Invariants that must hold for every golden question
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question,_expected", GOLDEN_ROUTING)
def test_no_metric_ever_reports_zero_for_missing_data(board_data, question, _expected):
    """A value of 0 must mean 'genuinely zero', never 'we didn't know'."""
    _, result, _ = answer(board_data, question)
    for metric in result.metrics:
        if metric.unit == "inr" and metric.value == 0:
            assert metric.rows_included > 0, (
                f"{metric.key} reported ₹0 with no contributing rows -- that is "
                "missing data wearing a number's clothes"
            )


@pytest.mark.parametrize("question,_expected", GOLDEN_ROUTING)
def test_every_metric_can_account_for_its_rows(board_data, question, _expected):
    _, result, _ = answer(board_data, question)
    for metric in result.metrics:
        assert metric.rows_included <= metric.rows_considered, metric.key
        if metric.rows_excluded:
            assert metric.exclusion_reasons, (
                f"{metric.key} excluded {metric.rows_excluded} rows without saying why"
            )


@pytest.mark.parametrize("question,_expected", GOLDEN_ROUTING)
def test_confidence_is_always_scored(board_data, question, _expected):
    _, result, _ = answer(board_data, question)
    assert result.ledger.confidence in ("high", "medium", "low")
