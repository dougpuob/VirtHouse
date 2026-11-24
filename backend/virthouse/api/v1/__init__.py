"""API v1 routers."""

from fastapi import APIRouter

from virthouse.api.v1 import builds, config, health, history, images, resources, vms

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(config.router)
api_v1_router.include_router(images.router)
api_v1_router.include_router(resources.router)
api_v1_router.include_router(history.router)
api_v1_router.include_router(vms.router)
api_v1_router.include_router(builds.router)
