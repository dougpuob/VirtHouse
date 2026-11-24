"""Image catalog API. Reads config/images.yaml, not system.yaml."""

from __future__ import annotations

from fastapi import APIRouter, Request

from virthouse.config.images import ImageCatalog

router = APIRouter(prefix="/images", tags=["images"])


@router.get("", response_model=ImageCatalog)
async def get_images(request: Request) -> ImageCatalog:
    """Return build status and usable-image status."""
    return request.app.state.images
