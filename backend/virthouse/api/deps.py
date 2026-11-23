"""FastAPI dependency helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from virthouse.config.models import SystemConfig
from virthouse.vm.manager import VmManager


def get_config(request: Request) -> SystemConfig:
    """Return the SystemConfig attached at application startup."""
    return request.app.state.config


def get_vms(request: Request) -> VmManager:
    """Return the VM manager attached at application startup."""
    return request.app.state.vms


ConfigDep = Annotated[SystemConfig, Depends(get_config)]
