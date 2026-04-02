"""FastAPI server for multi-machine claudewatch data ingestion and query."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from claudewatch.models import QuotaEvent, UsageRecord
from claudewatch.storage.sqlite import (
    init_db,
    insert_quota_event,
    insert_usage,
    read_active_sessions,
    read_today_usage,
    read_usage,
)


# --- Request/response models ---


class UsageRecordCreate(BaseModel):
    """Ingest payload for a usage record."""

    timestamp: datetime
    session_id: str
    machine_id: str = ""
    model: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    project: str = "unknown"
    service_tier: str = "standard"
    speed: str = "standard"
    user_id: str = "default"
    slug: str = ""


class QuotaEventCreate(BaseModel):
    """Ingest payload for a quota event."""

    timestamp: datetime
    event_type: str
    cumulative_input: int = 0
    cumulative_output: int = 0
    message: str = ""
    machine_id: str = ""
    user_id: str = "default"


class StatusResponse(BaseModel):
    status: str = "ok"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"


# --- App factory ---


def create_app(db_path: Path, auth_token: str) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(title="claudewatch", version="0.2.0")

    # Initialize database on startup
    init_db(db_path)

    # --- Auth dependency ---

    def verify_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if authorization is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing auth token")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or token != auth_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token")

    authed = [Depends(verify_token)]

    # --- Endpoints ---

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.post(
        "/api/usage",
        response_model=StatusResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=authed,
    )
    def post_usage(payload: UsageRecordCreate) -> StatusResponse:
        record = UsageRecord(
            timestamp=payload.timestamp,
            session_id=payload.session_id,
            model=payload.model,
            input_tokens=payload.input_tokens,
            output_tokens=payload.output_tokens,
            cache_read_input_tokens=payload.cache_read_input_tokens,
            cache_creation_input_tokens=payload.cache_creation_input_tokens,
            project=payload.project,
            service_tier=payload.service_tier,
            speed=payload.speed,
            user_id=payload.user_id,
            slug=payload.slug,
            machine_id=payload.machine_id,
        )
        insert_usage(db_path, record)
        return StatusResponse()

    @app.post(
        "/api/quota",
        response_model=StatusResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=authed,
    )
    def post_quota(payload: QuotaEventCreate) -> StatusResponse:
        event = QuotaEvent(
            timestamp=payload.timestamp,
            event_type=payload.event_type,
            cumulative_input=payload.cumulative_input,
            cumulative_output=payload.cumulative_output,
            message=payload.message,
            user_id=payload.user_id,
            machine_id=payload.machine_id,
        )
        insert_quota_event(db_path, event)
        return StatusResponse()

    @app.get("/api/sessions/active", dependencies=authed)
    def get_active_sessions(minutes: int = 10) -> list[dict]:
        return read_active_sessions(db_path, minutes=minutes)

    @app.get("/api/usage/today", dependencies=authed)
    def get_today_usage() -> list[dict]:
        records = read_today_usage(db_path)
        return [r.model_dump(mode="json") for r in records]

    @app.get("/api/usage/session/{session_id}", dependencies=authed)
    def get_session_records(session_id: str) -> list[dict]:
        all_records = read_usage(db_path)
        return [
            r.model_dump(mode="json")
            for r in all_records
            if r.session_id == session_id
        ]

    return app
