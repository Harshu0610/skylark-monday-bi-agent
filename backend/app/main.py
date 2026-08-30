"""FastAPI application entry point.

All secrets live on this side of the wire. The browser talks only to this
service; it never sees a Monday token or an LLM key.
"""
from __future__ import annotations

import logging

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import chat, health
from .config import get_settings

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("skylark")

app = FastAPI(
    title="Skylark Business Intelligence",
    description=(
        "Conversational BI over Monday.com. Read-only: this service issues "
        "GraphQL queries and never mutations."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(health.router, prefix="/api", tags=["health"])


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace or configuration detail to the client."""
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Something went wrong while answering that question.",
            "detail": "The error has been logged. Please try again.",
        },
    )


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Skylark BI starting")
    logger.info("  Monday configured : %s", settings.monday_configured)
    logger.info("  LLM provider      : %s (configured: %s)",
                settings.llm_provider, settings.llm_configured)
    if not settings.monday_configured:
        logger.warning("MONDAY_API_TOKEN is not set - board queries will fail")
    if not settings.llm_configured:
        logger.warning("No LLM key set - keyword routing and template answers will be used")


# The UI is served by this same service. One deployment instead of two, no
# CORS surface, and no build step -- which keeps the demo URL reliable.
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
else:
    @app.get("/")
    async def root() -> dict:
        logger.warning("frontend directory not found at %s", FRONTEND_DIR)
        return {"service": "Skylark Business Intelligence", "docs": "/docs",
                "health": "/api/health"}
