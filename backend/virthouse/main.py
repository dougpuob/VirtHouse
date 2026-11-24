"""VirtHouse FastAPI application entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from virthouse import __version__
from virthouse.api.v1 import api_v1_router
from virthouse.config import load_config
from virthouse.config.images import ImageCatalog, load_images
from virthouse.config.models import SystemConfig
from virthouse.history.store import HistoryStore
from virthouse.host.display import HostDisplay
from virthouse.build.errors import BuildError, BuildNotFound
from virthouse.build.runner import BuildRunner
from virthouse.vm.errors import VmError, VmNotFound
from virthouse.vm.manager import VmManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("virthouse")


_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def create_app(
    config: SystemConfig | None = None,
    manager: VmManager | None = None,
    images: ImageCatalog | None = None,
    history: HistoryStore | None = None,
    display: HostDisplay | None = None,
    builds: BuildRunner | None = None,
) -> FastAPI:
    """Build the FastAPI app, optionally with a pre-loaded config (for tests)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = config if config is not None else load_config()
        store = history if history is not None else HistoryStore(Path(cfg.paths.history))
        app.state.config = cfg
        app.state.images = images if images is not None else load_images()
        app.state.history = store
        app.state.vms = manager if manager is not None else VmManager(cfg, history=store)
        app.state.builds = builds if builds is not None else BuildRunner()
        app.state.display = display if display is not None else HostDisplay()
        try:
            store.record(
                level="information",
                action="host.started",
                subject_kind="host",
                subject_name="VirtHouse",
                message="Backend process started. History database opened.",
            )
        except Exception:
            logger.exception("history record failed")
        logger.info(
            "VirtHouse %s ready (qemu=%s, overlays=%s)",
            __version__,
            cfg.qemu.binary,
            cfg.paths.overlays,
        )
        yield
        shutdown = getattr(app.state.vms, "shutdown", None)
        if shutdown is not None:
            await shutdown()
        await app.state.builds.shutdown()
        app.state.display.close()
        store.close()

    app = FastAPI(
        title="VirtHouse",
        description="QEMU multi-instance management system",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(api_v1_router)

    index = _FRONTEND / "index.html"

    @app.get("/")
    async def home() -> FileResponse:
        return FileResponse(index)

    if _FRONTEND.is_dir():
        app.mount("/ui", StaticFiles(directory=_FRONTEND, html=True), name="ui")

    @app.exception_handler(VmNotFound)
    async def vm_not_found(_request: Request, exc: VmNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(VmError)
    async def vm_error(_request: Request, exc: VmError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(BuildNotFound)
    async def build_not_found(_request: Request, exc: BuildNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(BuildError)
    async def build_error(_request: Request, exc: BuildError) -> JSONResponse:
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
