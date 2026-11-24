"""SQLite history of operator actions on this host."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from virthouse.history.models import HistoryEntry, HistoryScope, HistoryView

LEVELS = ("error", "warning", "information")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ROW_LIMIT = 500
_KEEP_DAYS = 90

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('error', 'warning', 'information')),
    action TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT,
    subject_name TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS history_day ON history (local_date, id DESC);
CREATE INDEX IF NOT EXISTS history_subject ON history (subject_kind, subject_id, generation);
"""


class HistoryStore:
    """One writer: the VirtHouse backend process."""

    def __init__(self, path: Path, *, keep_days: int = _KEEP_DAYS) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._keep_days = keep_days
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self.prune()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def record(
        self,
        *,
        level: str,
        action: str,
        subject_kind: str,
        message: str,
        subject_id: str | None = None,
        subject_name: str | None = None,
        generation: int = 0,
        detail: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> int:
        """Append one row. ``at`` defaults to now and is for tests."""
        if level not in LEVELS:
            raise ValueError(f"unknown history level: {level}")
        moment = at if at is not None else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        local_day = moment.astimezone().date().isoformat()
        payload = json.dumps(detail, sort_keys=True) if detail else None
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO history (
                    at, local_date, level, action, subject_kind,
                    subject_id, subject_name, generation, message, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    moment.astimezone(timezone.utc).isoformat(),
                    local_day,
                    level,
                    action,
                    subject_kind,
                    subject_id,
                    subject_name,
                    generation,
                    message,
                    payload,
                ),
            )
            self._conn.commit()
            row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("history insert did not return an id")
        return int(row_id)

    def prune(self, *, today: date | None = None) -> int:
        """Delete rows older than the retention window. Returns how many went."""
        day = today or _today()
        cutoff = (day - timedelta(days=self._keep_days)).isoformat()
        with self._lock:
            cursor = self._conn.execute("DELETE FROM history WHERE local_date < ?", (cutoff,))
            self._conn.commit()
            return cursor.rowcount

    def query(
        self,
        *,
        scope: str,
        levels: list[str] | None,
        q: str,
        live: list[tuple[str, str, int]],
        now: datetime | None = None,
    ) -> HistoryView:
        """Return one time scope. Rail counts ignore level and search."""
        moment = now if now is not None else datetime.now(timezone.utc)
        today = moment.astimezone().date()
        yesterday = today - timedelta(days=1)
        chosen = _resolve_levels(levels)
        where, params = _scope_clause(scope, today, live)
        like = _like_clause(q)
        with self._lock:
            scopes = self._scopes(today, live)
            level_counts = self._level_counts(where, params)
            current_errors = self._count(f"{_current_sql(live)} AND level = 'error'", _current_params(today, live))
            listed = self._entries(where, params, chosen, like)
        entries = [_entry(row, live, today) for row in listed[:_ROW_LIMIT]]
        return HistoryView(
            today=today.isoformat(),
            yesterday=yesterday.isoformat(),
            current_errors=current_errors,
            scopes=scopes,
            levels=level_counts,
            shown=len(entries),
            truncated=len(listed) > _ROW_LIMIT,
            entries=entries,
        )

    def _scopes(self, today: date, live: list[tuple[str, str, int]]) -> list[HistoryScope]:
        counts = {
            row["local_date"]: int(row["n"])
            for row in self._conn.execute("SELECT local_date, COUNT(*) AS n FROM history GROUP BY local_date")
        }
        yesterday = today - timedelta(days=1)
        scopes = [
            HistoryScope(id="current", label="Current", count=self._count(_current_sql(live), _current_params(today, live))),
            HistoryScope(id="today", label="Today", count=counts.get(today.isoformat(), 0)),
            HistoryScope(id="yesterday", label="Yesterday", count=counts.get(yesterday.isoformat(), 0)),
        ]
        older = sorted((day for day in counts if day not in {today.isoformat(), yesterday.isoformat()}), reverse=True)
        for raw in older:
            day = date.fromisoformat(raw)
            label = f"{_MONTHS[day.month - 1]} {day.day}"
            if day.year != today.year:
                label = f"{label}, {day.year}"
            scopes.append(HistoryScope(id=raw, label=label, count=counts[raw]))
        return scopes

    def _level_counts(self, where: str, params: list[Any]) -> dict[str, int]:
        found = {
            row["level"]: int(row["n"])
            for row in self._conn.execute(
                f"SELECT level, COUNT(*) AS n FROM history WHERE {where} GROUP BY level",
                params,
            )
        }
        return {level: found.get(level, 0) for level in LEVELS}

    def _count(self, where: str, params: list[Any]) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM history WHERE {where}", params).fetchone()
        return int(row["n"]) if row is not None else 0

    def _entries(
        self,
        where: str,
        params: list[Any],
        levels: tuple[str, ...],
        like: tuple[str, list[str]] | None,
    ) -> list[sqlite3.Row]:
        marks = ", ".join("?" for _ in levels)
        sql = f"SELECT * FROM history WHERE {where} AND level IN ({marks})"
        bound = [*params, *levels]
        if like is not None:
            clause, extra = like
            sql += f" AND {clause}"
            bound.extend(extra)
        sql += " ORDER BY id DESC LIMIT ?"
        bound.append(_ROW_LIMIT + 1)
        return list(self._conn.execute(sql, bound))


def _today() -> date:
    return datetime.now(timezone.utc).astimezone().date()


def _resolve_levels(levels: list[str] | None) -> tuple[str, ...]:
    if not levels:
        return LEVELS
    unknown = [level for level in levels if level not in LEVELS]
    if unknown:
        raise ValueError(f"unknown history level: {unknown[0]}")
    return tuple(dict.fromkeys(levels))


def _resolve_scope(scope: str, today: date) -> tuple[str, str | None]:
    if scope == "current":
        return "current", None
    if scope == "today":
        return "day", today.isoformat()
    if scope == "yesterday":
        return "day", (today - timedelta(days=1)).isoformat()
    try:
        day = date.fromisoformat(scope)
    except ValueError as exc:
        raise ValueError(f"unknown history scope: {scope}") from exc
    if day.isoformat() != scope:
        raise ValueError(f"unknown history scope: {scope}")
    return "day", scope


def _current_sql(live: list[tuple[str, str, int]]) -> str:
    parts = [
        "(local_date = ? AND subject_kind = 'host')",
        "(local_date = ? AND level = 'error')",
    ]
    for kind, _subject_id, _generation in live:
        if kind == "vm":
            parts.append("(subject_kind = 'vm' AND subject_id = ? AND generation = ?)")
        elif kind in {"device", "build"}:
            parts.append("(subject_kind = ? AND subject_id = ?)")
    return "(" + " OR ".join(parts) + ")"


def _current_params(today: date, live: list[tuple[str, str, int]]) -> list[Any]:
    params: list[Any] = [today.isoformat(), today.isoformat()]
    for kind, subject_id, generation in live:
        if kind == "vm":
            params.extend([subject_id, generation])
        elif kind in {"device", "build"}:
            params.extend([kind, subject_id])
    return params


def _scope_clause(scope: str, today: date, live: list[tuple[str, str, int]]) -> tuple[str, list[Any]]:
    kind, day = _resolve_scope(scope, today)
    if kind == "current":
        return _current_sql(live), _current_params(today, live)
    return "local_date = ?", [day]


def _like_clause(q: str) -> tuple[str, list[str]] | None:
    text = q.strip().lower()
    if not text:
        return None
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    clause = """(
        lower(message) LIKE ? ESCAPE '\\'
        OR lower(ifnull(subject_name, '')) LIKE ? ESCAPE '\\'
        OR lower(action) LIKE ? ESCAPE '\\'
    )"""
    return clause, [pattern, pattern, pattern]


def _is_current(row: sqlite3.Row, live: list[tuple[str, str, int]], today: date) -> bool:
    local_date = str(row["local_date"])
    if local_date == today.isoformat() and str(row["subject_kind"]) == "host":
        return True
    if local_date == today.isoformat() and str(row["level"]) == "error":
        return True
    for kind, subject_id, generation in live:
        if (
            kind == "vm"
            and row["subject_kind"] == "vm"
            and row["subject_id"] == subject_id
            and int(row["generation"]) == generation
        ):
            return True
        if kind in {"device", "build"} and row["subject_kind"] == kind and row["subject_id"] == subject_id:
            return True
    return False


def _entry(row: sqlite3.Row, live: list[tuple[str, str, int]], today: date) -> HistoryEntry:
    raw_detail = row["detail"]
    detail = json.loads(raw_detail) if raw_detail else None
    return HistoryEntry(
        id=int(row["id"]),
        at=str(row["at"]),
        local_date=str(row["local_date"]),
        level=str(row["level"]),
        action=str(row["action"]),
        subject_kind=str(row["subject_kind"]),
        subject_id=row["subject_id"],
        subject_name=row["subject_name"],
        generation=int(row["generation"]),
        message=str(row["message"]),
        detail=detail,
        current=_is_current(row, live, today),
    )
