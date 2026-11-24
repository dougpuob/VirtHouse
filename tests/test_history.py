"""History scopes, levels, and the rows a refused start leaves behind."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from virthouse.config.loader import load_config
from virthouse.history.store import HistoryStore
from virthouse.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(tmp_path / "history.db")


def _local_now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _record(store: HistoryStore, **kwargs: object) -> None:
    fields = {
        "level": "information",
        "action": "vm.start",
        "subject_kind": "vm",
        "message": "started",
    }
    fields.update(kwargs)
    store.record(**fields)  # type: ignore[arg-type]


def test_current_keeps_this_boot_and_todays_errors(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = _local_now()
    yesterday = now - timedelta(days=1)
    _record(
        store,
        at=yesterday,
        subject_id="vm1",
        subject_name="ubuntu2404",
        generation=1,
        message="first boot",
    )
    _record(
        store,
        at=now,
        subject_id="vm1",
        subject_name="ubuntu2404",
        generation=2,
        message="second boot",
    )
    _record(
        store,
        at=yesterday,
        subject_id="vm1",
        subject_name="ubuntu2404",
        generation=2,
        level="information",
        action="vm.ready",
        message="still up from yesterday",
    )
    _record(
        store,
        level="error",
        subject_name="win11-test",
        message="memory insufficient (need 8192MB, available 4096MB)",
        at=now,
    )
    _record(
        store,
        level="information",
        action="vm.delete",
        subject_id="gone",
        subject_name="ci-runner",
        message="Stopped ci-runner and deleted its overlay.",
        at=now,
    )

    current = store.query(scope="current", levels=None, q="", live=[("vm", "vm1", 2)], now=now)
    messages = [entry.message for entry in current.entries]
    assert "second boot" in messages
    assert "still up from yesterday" in messages
    assert "memory insufficient (need 8192MB, available 4096MB)" in messages
    assert "first boot" not in messages
    assert "Stopped ci-runner and deleted its overlay." not in messages
    assert current.current_errors == 1
    assert current.scopes[0].id == "current"
    assert current.scopes[1].id == "today"
    assert current.scopes[2].id == "yesterday"

    today = store.query(scope="today", levels=None, q="", live=[("vm", "vm1", 2)], now=now)
    today_messages = [entry.message for entry in today.entries]
    assert "first boot" not in today_messages
    assert "Stopped ci-runner and deleted its overlay." in today_messages
    assert any(entry.current for entry in today.entries if "memory insufficient" in entry.message)


def test_level_and_search_do_not_change_the_rail(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = _local_now()
    _record(store, level="error", subject_name="scratch", message="base image missing", at=now)
    _record(store, level="information", action="config.save", subject_kind="host", subject_name="system.yaml", message="saved settings", at=now)
    full = store.query(scope="today", levels=None, q="", live=[], now=now)
    errors = store.query(scope="today", levels=["error"], q="", live=[], now=now)
    found = store.query(scope="today", levels=None, q="scratch", live=[], now=now)
    assert [scope.count for scope in errors.scopes] == [scope.count for scope in full.scopes]
    assert [scope.count for scope in found.scopes] == [scope.count for scope in full.scopes]
    assert errors.levels == full.levels
    assert [entry.level for entry in errors.entries] == ["error"]
    assert [entry.subject_name for entry in found.entries] == ["scratch"]


def test_older_empty_days_are_omitted_and_expired_rows_go(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = _local_now()
    old = now - timedelta(days=100)
    kept = now - timedelta(days=10)
    _record(store, message="ancient", at=old)
    _record(store, message="recent", at=kept, subject_name="kept")
    assert store.prune(today=now.date()) == 1
    view = store.query(scope="current", levels=None, q="", live=[], now=now)
    ids = [scope.id for scope in view.scopes]
    assert ids[:3] == ["current", "today", "yesterday"]
    assert old.date().isoformat() not in ids
    assert kept.date().isoformat() in ids
    day = store.query(scope=kept.date().isoformat(), levels=None, q="", live=[], now=now)
    assert [entry.message for entry in day.entries] == ["recent"]


def test_refused_start_is_a_current_error() -> None:
    cfg = load_config(REPO_ROOT / "config" / "system.yaml")
    cfg.resources.reserve_memory_mb = 10**9
    app = create_app(cfg)
    with TestClient(app) as client:
        refused = client.post(
            "/api/v1/vms",
            json={"name": "win11-test", "base_image": "base.qcow2", "cpus": 1, "memory_mb": 512},
        )
        assert refused.status_code == 400
        history = client.get("/api/v1/history")
        assert history.status_code == 200
        body = history.json()
        assert body["scopes"][0]["id"] == "current"
        assert body["current_errors"] == 1
        assert "memory insufficient" in body["entries"][0]["message"]
        assert body["entries"][0]["current"] is True
        narrowed = client.get("/api/v1/history", params=[("scope", "today"), ("level", "error"), ("q", "win11")])
        assert narrowed.status_code == 200
        assert len(narrowed.json()["entries"]) == 1
        assert narrowed.json()["scopes"][1]["count"] == body["scopes"][1]["count"]
        unknown = client.get("/api/v1/history", params={"scope": "later"})
        assert unknown.status_code == 400
