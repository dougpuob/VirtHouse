"""Operator history for this host."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from virthouse.history.models import HistoryView
from virthouse.history.store import HistoryStore

router = APIRouter(prefix="/history", tags=["history"])


def _store(request: Request) -> HistoryStore:
    return request.app.state.history


@router.get("", response_model=HistoryView)
def get_history(
    request: Request,
    scope: str = "current",
    level: Annotated[list[str], Query()] = [],
    q: str = "",
) -> HistoryView:
    """Return one time scope. An empty level list means every level."""
    manager = request.app.state.vms
    live = manager.live_subjects() if hasattr(manager, "live_subjects") else []
    try:
        return _store(request).query(scope=scope, levels=level, q=q, live=live)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
