"""The /api/chat endpoint: question in, structured executive answer out."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter

from ..agent import narrator, planner
from ..agent.executor import DataService, execute
from ..llm.base import LLMError, get_provider
from ..models.schemas import ChatRequest, ChatResponse, QualityLedger
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

_data_service: DataService | None = None


def get_data_service() -> DataService:
    global _data_service
    if _data_service is None:
        _data_service = DataService()
    return _data_service


def _provider():
    settings = get_settings()
    if not settings.llm_configured:
        return None
    try:
        return get_provider()
    except LLMError as exc:
        logger.warning("LLM provider unavailable: %s", exc)
        return None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    request_id = uuid.uuid4().hex[:12]
    question = request.message.strip()

    logger.info("[%s] question=%r", request_id, question[:200])
    provider = _provider()

    # 1. Plan. The planner sees the question only -- never board data.
    outcome = await planner.build_plan(question, request.history, provider)
    if outcome.clarification:
        logger.info("[%s] clarification requested", request_id)
        return ChatResponse(
            answer=outcome.clarification,
            clarification=outcome.clarification,
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    plan = outcome.plan
    assert plan is not None
    logger.info("[%s] intent=%s boards=%s filters=%s", request_id, plan.intent.value,
                [b.value for b in plan.boards], plan.filters.model_dump(exclude_none=True))

    # 2. Fetch and normalize.
    service = get_data_service()
    bundle = await service.load(plan.boards)
    if bundle.fatal:
        logger.error("[%s] data unavailable: %s", request_id, bundle.fatal)
        return ChatResponse(
            answer=bundle.fatal,
            risks=bundle.warnings,
            plan=plan,
            ledger=QualityLedger(confidence="low", warnings=bundle.warnings),
            degraded=True,
            degraded_reason=bundle.fatal,
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # 3. Compute. Deterministic; no LLM below this line.
    result = execute(plan, bundle)
    logger.info("[%s] metrics=%d confidence=%s rows=%d/%d", request_id,
                len(result.metrics), result.ledger.confidence,
                result.ledger.rows_included, result.ledger.rows_considered)

    # 4. Narrate. Aggregates only, fenced as untrusted, numbers verified.
    narrative, degraded, reason = await narrator.narrate(result, plan, question, provider)

    degraded = degraded or outcome.degraded
    reason = reason or outcome.degraded_reason

    duration = int((time.perf_counter() - started) * 1000)
    logger.info("[%s] done in %dms degraded=%s", request_id, duration, degraded)

    return ChatResponse(
        answer=narrative["answer"],
        insight=narrative.get("insight"),
        risks=narrative.get("risks", []),
        metrics=result.metrics,
        breakdowns=result.breakdowns,
        ledger=result.ledger,
        plan=plan,
        assumptions=plan.assumptions,
        follow_ups=narrative.get("follow_ups", []),
        degraded=degraded,
        degraded_reason=reason,
        request_id=request_id,
        duration_ms=duration,
    )
