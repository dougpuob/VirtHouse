"""Keep history databases opened by the app inside each test's tmp directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from virthouse.history.store import HistoryStore


@pytest.fixture(autouse=True)
def isolated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def open_store(_path: Path) -> HistoryStore:
        return HistoryStore(tmp_path / "history.db")

    monkeypatch.setattr("virthouse.main.HistoryStore", open_store)
