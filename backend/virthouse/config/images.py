"""Image catalog. Separate from system.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from virthouse.config.loader import DEFAULT_CONFIG_PATH

DEFAULT_IMAGES_PATH = DEFAULT_CONFIG_PATH.parent / "images.yaml"


class BuildRecord(BaseModel):
    """One Packer build and its status. Empty until a build is set up."""

    name: str
    status: str


class UsableImage(BaseModel):
    """A disk a machine may start from. ``file`` is the name inside the bases directory."""

    name: str
    file: str
    status: str


class ImageCatalog(BaseModel):
    builds: list[BuildRecord] = Field(default_factory=list)
    images: list[UsableImage] = Field(default_factory=list)


def load_images(path: str | Path | None = None) -> ImageCatalog:
    """Load the image catalog. This is not the VirtHouse process config."""
    catalog_path = Path(path).expanduser().resolve() if path is not None else DEFAULT_IMAGES_PATH.resolve()
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Image catalog not found: {catalog_path}")
    with catalog_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Image catalog root must be a mapping, got {type(raw).__name__}")
    return ImageCatalog.model_validate(raw)
