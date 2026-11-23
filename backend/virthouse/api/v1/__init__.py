"""API v1 routers."""

from fastapi import APIRouter

from virthouse.api.v1 import config, health, vms

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(config.router)
api_v1_router.include_router(vms.router)
