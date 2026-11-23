"""Config API (DESIGN_v3.md section 11 — Config)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from virthouse.config.models import SystemConfig

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=SystemConfig)
async def get_config(request: Request) -> SystemConfig:
    """Return the currently loaded system configuration."""
    return request.app.state.config
