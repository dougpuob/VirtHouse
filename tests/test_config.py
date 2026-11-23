"""Config loading tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from virthouse.config.loader import load_config
from virthouse.config.models import SystemConfig
from virthouse.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YAML = REPO_ROOT / "config" / "default.yaml"


def test_load_default_config() -> None:
    cfg = load_config(DEFAULT_YAML)
    assert isinstance(cfg, SystemConfig)
    assert cfg.paths.overlays.endswith("overlays")
    assert cfg.qemu.binary == "qemu-system-x86_64"
    assert cfg.timeouts.overall_sec == 600
    assert cfg.server.port == 8080


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_health_and_config_endpoints() -> None:
    cfg = load_config(DEFAULT_YAML)
    app = create_app(config=cfg)
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        config_resp = client.get("/api/v1/config")
        assert config_resp.status_code == 200
        body = config_resp.json()
        assert body["qemu"]["binary"] == cfg.qemu.binary
        assert body["paths"]["bases"] == cfg.paths.bases

        vms = client.get("/api/v1/vms")
        assert vms.status_code == 200
        assert vms.json() == []
