"""Start a Packer build and show its display."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response

from virthouse.api.deps import ConfigDep
from virthouse.build.models import BuildRequest, BuildView
from virthouse.build.runner import BuildRunner
from virthouse.vm.vnc import proxy_vnc

router = APIRouter(prefix="/builds", tags=["builds"])


def _runner(request: Request) -> BuildRunner:
    return request.app.state.builds


@router.get("", response_model=list[BuildView])
async def list_builds(request: Request) -> list[BuildView]:
    """Packs this process has started, newest first."""
    return _runner(request).list()


@router.post("", response_model=BuildView, status_code=201)
async def start_build(body: BuildRequest, request: Request, config: ConfigDep) -> BuildView:
    """Run Packer on this template. Screenshots show up as the display changes."""
    return await _runner(request).start(
        name=body.name,
        hcl=body.hcl,
        work=Path(config.paths.work),
        history=request.app.state.history,
    )


@router.get("/{build_id}", response_model=BuildView)
async def get_build(build_id: str, request: Request) -> BuildView:
    return _runner(request).get(build_id)


@router.post("/{build_id}/cancel", response_model=BuildView)
async def cancel_build(build_id: str, request: Request) -> BuildView:
    """Stop Packer and the QEMU it started."""
    return await _runner(request).cancel(build_id)


@router.websocket("/{build_id}/vnc")
async def build_vnc(websocket: WebSocket, build_id: str) -> None:
    """View-only noVNC connects here. Bytes are forwarded to Packer's QEMU."""
    port = _runner(websocket).live_vnc_port(build_id)
    if port is None:
        await websocket.close(code=1008)
        return
    await proxy_vnc(websocket, "127.0.0.1", port)


@router.get("/{build_id}/screen/{name}")
async def build_screen(build_id: str, name: str, request: Request) -> Response:
    """One PNG from this pack. ``latest.png`` is the current display."""
    path = _runner(request).screen_path(build_id, name)
    if path is None or not path.is_file():
        return JSONResponse(status_code=404, content={"detail": "That screenshot is not on this pack."})
    headers = {"Cache-Control": "no-store"} if name == "latest.png" else {"Cache-Control": "public, max-age=86400"}
    return FileResponse(path, media_type="image/png", headers=headers)
