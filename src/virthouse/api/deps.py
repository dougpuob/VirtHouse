"""FastAPI dependency helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from virthouse.config.models import SystemConfig


def get_config(request: Request) -> SystemConfig:
    """Return the SystemConfig attached at application startup."""
    return request.app.state.config


ConfigDep = Annotated[SystemConfig, Depends(get_config)]
