"""Tests for the dashboard endpoints (/api/overview, /api/data-quality, /api/insights, /api/reports, /api/records)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_overview_endpoint(client: TestClient) -> None:
    res = client.get("/api/overview")
    assert res.status_code == 200
    data = res.json()
    assert "cards" in data
    assert len(data["cards"]) >= 4
    for card in data["cards"]:
        assert "key" in card
        assert "label" in card
        assert "display" in card
        assert "provenance" in card
    assert "suggested_questions" in data
    assert len(data["suggested_questions"]) >= 6
    assert "secondary" in data


def test_data_quality_endpoint(client: TestClient) -> None:
    res = client.get("/api/data-quality")
    assert res.status_code == 200
    data = res.json()
    assert "health_score" in data
    assert 0 <= data["health_score"] <= 100
    assert "deals_missing" in data
    assert "wo_missing" in data
    assert "coverage" in data


def test_insights_endpoint(client: TestClient) -> None:
    res = client.get("/api/insights")
    assert res.status_code == 200
    data = res.json()
    assert "sector_matrix" in data
    assert "accounts_at_risk" in data
    assert "owner_cross" in data
    assert "coverage" in data


def test_reports_endpoint(client: TestClient) -> None:
    res = client.get("/api/reports")
    assert res.status_code == 200
    data = res.json()
    assert "period_label" in data
    assert "talking_points" in data
    assert len(data["talking_points"]) > 0
    assert "ranked_risks" in data
    assert "quarterly_trend" in data
    assert "funnel_stage" in data


def test_records_endpoint(client: TestClient) -> None:
    res = client.get("/api/records?board=deals&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["board"] == "deals"
    assert "records" in data
    assert len(data["records"]) <= 10

    res_wo = client.get("/api/records?board=work_orders&limit=10")
    assert res_wo.status_code == 200
    data_wo = res_wo.json()
    assert data_wo["board"] == "work_orders"
    assert "records" in data_wo
    assert len(data_wo["records"]) <= 10

