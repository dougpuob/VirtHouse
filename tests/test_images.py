"""Image catalog is a separate file from system.yaml."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from virthouse.config.images import DEFAULT_IMAGES_PATH, load_images
from virthouse.config.loader import load_config
from virthouse.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_images_catalog_is_not_system_yaml() -> None:
    assert DEFAULT_IMAGES_PATH == REPO_ROOT / "config" / "images.yaml"
    catalog = load_images()
    assert catalog.builds == []
    assert catalog.images[0].name == "ubuntu2404-q35"
    assert catalog.images[0].file == "ubuntu2404-q35.qcow2"
    assert catalog.images[0].status == "usable"
    served = json.loads((REPO_ROOT / "frontend" / "images.json").read_text(encoding="utf-8"))
    assert served == catalog.model_dump()


def test_images_endpoint_leaves_system_config_alone() -> None:
    cfg = load_config(REPO_ROOT / "config" / "system.yaml")
    app = create_app(config=cfg)
    with TestClient(app) as client:
        images = client.get("/api/v1/images")
        config = client.get("/api/v1/config")
    assert images.status_code == 200
    body = images.json()
    assert body["builds"] == []
    assert body["images"][0]["status"] == "usable"
    assert "builds" not in config.json()
    assert "images" not in config.json()
