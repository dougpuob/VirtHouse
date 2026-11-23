"""Load system configuration from YAML."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from virthouse.config.models import SystemConfig

logger = logging.getLogger(__name__)

ENV_CONFIG_PATH = "VIRTHOUSE_CONFIG"

# Repo-relative default: <repo>/config/default.yaml
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "default.yaml"


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    """Resolve config file path: explicit arg > env > default.yaml."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()

    env_path = os.environ.get(ENV_CONFIG_PATH)
    if env_path:
        return Path(env_path).expanduser().resolve()

    return DEFAULT_CONFIG_PATH.resolve()


def load_config(path: str | Path | None = None) -> SystemConfig:
    """Load and validate SystemConfig from a YAML file."""
    config_path = resolve_config_path(path)

    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {config_path} "
            f"(set {ENV_CONFIG_PATH} or place config at {DEFAULT_CONFIG_PATH})"
        )

    logger.info("Loading config from %s", config_path)
    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Config root must be a mapping, got {type(raw).__name__}")

    return SystemConfig.model_validate(raw)
