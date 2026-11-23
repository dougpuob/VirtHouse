"""VirtHouse FastAPI application entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from virthouse import __version__
from virthouse.api.v1 import api_v1_router
from virthouse.config import load_config
from virthouse.config.models import SystemConfig
from virthouse.vm.errors import VmError, VmNotFound
from virthouse.vm.manager import VmManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("virthouse")


def create_app(config: SystemConfig | None = None) -> FastAPI:
    """Build the FastAPI app, optionally with a pre-loaded config (for tests)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = config if config is not None else load_config()
        app.state.config = cfg
        app.state.vms = VmManager(cfg)
        logger.info(
            "VirtHouse %s ready (qemu=%s, overlays=%s)",
            __version__,
            cfg.qemu.binary,
            cfg.paths.overlays,
        )
        yield
        await app.state.vms.shutdown()

    app = FastAPI(
        title="VirtHouse",
        description="QEMU multi-instance management system",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(api_v1_router)

    @app.exception_handler(VmNotFound)
    async def vm_not_found(_request: Request, exc: VmNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(VmError)
    async def vm_error(_request: Request, exc: VmError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()


def run() -> None:
    """CLI entry: `virthouse` or `python -m virthouse`."""
    load_config()
    host = os.environ.get("VIRTHOUSE_HOST", "0.0.0.0")
    port = int(os.environ.get("VIRTHOUSE_PORT", "8080"))
    uvicorn.run(
        "virthouse.main:app",
        host=host,
        port=port,
        reload=os.environ.get("VIRTHOUSE_RELOAD", "").lower() in ("1", "true"),
    )


if __name__ == "__main__":
    run()
