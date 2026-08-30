"""Health and board-freshness endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from ..config import get_settings
from ..models.schemas import HealthResponse
from .chat import get_data_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Configuration status. Never returns secret values, only whether they exist."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        monday_configured=settings.monday_configured,
        llm_configured=settings.llm_configured,
        llm_provider=settings.llm_provider,
    )


@router.get("/boards", response_model=HealthResponse)
async def boards() -> HealthResponse:
    """Board names, item counts and data freshness for the UI header."""
    settings = get_settings()
    statuses = []
    try:
        statuses = await get_data_service().board_statuses()
    except Exception as exc:  # noqa: BLE001 - the header must never break the page
        logger.warning("board status lookup failed: %s", exc)
    return HealthResponse(
        status="ok",
        monday_configured=settings.monday_configured,
        llm_configured=settings.llm_configured,
        llm_provider=settings.llm_provider,
        boards=statuses,
    )
