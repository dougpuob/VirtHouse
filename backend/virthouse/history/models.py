"""Rows and pages returned by the history store."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HistoryEntry(BaseModel):
    """One operator-visible action."""

    id: int
    at: str
    local_date: str
    level: str
    action: str
    subject_kind: str
    subject_id: str | None = None
    subject_name: str | None = None
    generation: int = 0
    message: str
    detail: dict[str, Any] | None = None
    current: bool = False


class HistoryScope(BaseModel):
    """One time bucket in the page rail."""

    id: str
    label: str
    count: int


class HistoryView(BaseModel):
    """The history page for one scope, after level and search filters."""

    today: str
    yesterday: str
    current_errors: int
    scopes: list[HistoryScope]
    levels: dict[str, int]
    shown: int
    truncated: bool
    entries: list[HistoryEntry] = Field(default_factory=list)
