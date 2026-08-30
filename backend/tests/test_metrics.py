"""Metric tests against fixtures with known answers.

The recurring theme: a missing value must reduce the denominator and be
reported, never be silently treated as zero.
"""
from __future__ import annotations

import pytest

from app.analytics import cross_board as cb
from app.analytics import deals as dm
from app.analytics import work_orders as wm


# ---------------------------------------------------------------------------
# Deal value metrics
# ---------------------------------------------------------------------------

def test_open_pipeline_excludes_missing_values_and_reports_them(deals):
    m = dm.total_open_pipeline(deals)
    assert m.value == pytest.approx(1_500_000)      # NOT 1.5M + 0 for Gamma
    assert m.rows_considered == 3                    # three open deals
    assert m.rows_included == 2                      # one has no value
    assert m.rows_excluded == 1
    assert "value is blank or unreadable" in m.exclusion_reasons


def test_open_pipeline_ignores_won_and_lost(deals):
    m = dm.total_open_pipeline(deals)
    assert m.value == pytest.approx(1_500_000)
    assert m.value != pytest.approx(3_800_000)       # would include Won + Lost


def test_weighted_pipeline_applies_probability(deals):
    # Alpha 1,000,000 x 0.75 (High) + Beta 500,000 x 0.45 (Medium)
    m = dm.weighted_pipeline(deals)
    assert m.value == pytest.approx(750_000 + 225_000)


def test_won_revenue_flags_the_missing_majority(deals):
    m = dm.won_revenue(deals)
    assert m.value == pytest.approx(2_000_000)
    assert m.rows_considered == 2
    assert m.rows_included == 1
    assert m.note and "no value recorded" in m.note


def test_missing_value_never_becomes_zero(deals):
    """The headline correctness guarantee of this system."""
    won = dm.won_revenue(deals)
    assert won.value == 2_000_000                    # not (2,000,000 + 0) / 2 averaging
    counts = dm.open_deal_count(deals)
    assert counts.value == 3                         # count still includes the blank one


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

def test_win_rate_uses_closed_deals_only(deals):
    m = dm.win_rate(deals)
    assert m.value == pytest.approx(2 / 3 * 100)     # 2 won of 3 closed
    assert m.rows_included == 3                      # open deals excluded


def test_win_rate_with_no_closed_deals_returns_none_not_zero_division(empty_deals):
    m = dm.win_rate(empty_deals)
    assert m.value is None
    assert m.display == "not available"
    assert "cannot be calculated" in (m.note or "")


def test_median_preferred_over_mean_on_skewed_values(deals):
    median = dm.median_deal_size(deals)
    mean = dm.average_deal_size(deals)
    assert median.value == pytest.approx(750_000)    # median of 1,000,000 and 500,000
    assert mean.value == pytest.approx(750_000)
    assert median.rows_included == 2


def test_concentration_reports_share_of_top_deals(deals):
    m = dm.pipeline_concentration(deals, top_n=1)
    assert m.value == pytest.approx(1_000_000 / 1_500_000 * 100)


# ---------------------------------------------------------------------------
# Empty data
# ---------------------------------------------------------------------------

def test_empty_board_refuses_a_number_rather_than_returning_zero(empty_deals):
    assert dm.total_open_pipeline(empty_deals).value is None
    assert dm.won_revenue(empty_deals).value is None
    assert dm.median_deal_size(empty_deals).value is None
    assert dm.open_deal_count(empty_deals).value == 0   # a count of zero IS a fact


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

def test_completed_includes_executed_until_current_month(work_orders):
    m = wm.completed_work_orders(work_orders)
    assert m.value == 3      # WO-1, WO-2 (recurring), WO-5


def test_delayed_excludes_rows_with_no_end_date(work_orders):
    m = wm.delayed_work_orders(work_orders)
    assert m.value == 1                              # only WO-3
    assert m.rows_included == 4                      # WO-4 has no end date
    assert "no planned end date, so delay cannot be determined" in m.exclusion_reasons
    assert m.note and "could not be assessed" in m.note


def test_completed_work_is_never_counted_as_delayed(work_orders):
    """WO-1 is past its end date but Completed -- delivered late is not 'delayed'."""
    row = work_orders[work_orders["wo_id"] == "WO-1"].iloc[0]
    assert row["is_complete"]
    assert not row["is_delayed"]


def test_completion_rate(work_orders):
    m = wm.completion_rate(work_orders)
    assert m.value == pytest.approx(3 / 5 * 100)


def test_completion_rate_with_no_work_orders_is_none(empty_work_orders):
    m = wm.completion_rate(empty_work_orders)
    assert m.value is None


def test_overdue_backlog_sums_only_delayed_value(work_orders):
    m = wm.overdue_backlog_value(work_orders)
    assert m.value == pytest.approx(900_000)         # WO-3 only


def test_unbilled_completed_finds_delivered_but_uninvoiced(work_orders):
    m = wm.unbilled_completed(work_orders)
    assert m.value == 1                              # WO-5: Completed, "Not billed yet"


def test_billing_gap_treats_unrecorded_billing_as_unbilled(work_orders):
    m = wm.billing_gap(work_orders)
    # WO-1 fully billed (0) + WO-2 500,000 + WO-3 900,000 + WO-4 200,000
    assert m.value == pytest.approx(1_600_000)


# ---------------------------------------------------------------------------
# Cross-board
# ---------------------------------------------------------------------------

def test_account_link_coverage_reports_unmatched(deals, work_orders):
    m = cb.account_link_coverage(deals, work_orders)
    # WO accounts: alpha, beta, delta, epsilon, orphan -> 4 of 5 match a deal
    assert m.value == pytest.approx(80.0)
    assert m.exclusion_reasons["work-order account has no matching deal"] == 1


def test_sector_matrix_labels_sectors_with_no_delivery_history(deals, work_orders):
    bd = cb.sector_opportunity_matrix(deals, work_orders)
    labels = {r.label: r.display["quadrant"] for r in bd.rows}
    assert "Mining" in labels
    assert any("no delivery" in q or q in
               ("Scale", "Fix delivery", "Underinvested", "Deprioritise",
                "Insufficient delivery data")
               for q in labels.values())


def test_account_join_does_not_multiply_rows(deals, work_orders):
    """A naive row-level merge on a non-unique key inflates every total.

    Deal name is an ACCOUNT alias, not a deal primary key, so both sides must be
    aggregated before joining.
    """
    bd = cb.accounts_at_risk(deals, work_orders)
    keys = [r.key for r in bd.rows]
    assert len(keys) == len(set(keys))


def test_customer_join_is_refused_not_faked():
    note = cb.customer_join_unavailable_note()
    assert "COMPANY" in note and "WOCOMPANY" in note
    assert "not possible" in note.lower()
