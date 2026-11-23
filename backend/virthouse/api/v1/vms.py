"""VM API stubs — implemented in a later stage (design.md section 11 — VM)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/vms", tags=["vms"])


@router.get("")
async def list_vms() -> list[dict]:
    """List running VMs. Placeholder until Stage 3."""
    return []
