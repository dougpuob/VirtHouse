"""Host resource API (DESIGN_v4.md section 11 — Resources)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.responses import JSONResponse, Response

from virthouse.api.deps import get_vms
from virthouse.host.display import HostDisplay
from virthouse.vm.manager import VmManager
from virthouse.vm.resources import HostResources
from virthouse.vm.vnc import proxy_vnc

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("", response_model=HostResources)
async def get_resources(manager: VmManager = Depends(get_vms)) -> HostResources:
    """Return this machine's CPU, memory, and the processes VirtHouse started."""
    return manager.host_view()


@router.get("/screen")
def host_screen(request: Request) -> Response:
    """Return the latest JPEG of this computer's desktop."""
    display: HostDisplay = request.app.state.display
    frame = display.frame()
    if not frame:
        return JSONResponse(status_code=503, content={"detail": display.problem() or "The host display is not available."})
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/screen/input", status_code=204)
async def host_screen_input(request: Request) -> Response:
    """Move the pointer, click, type, or scroll on this computer's desktop."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "Input must be an object."})
    request.app.state.display.send(body)
    return Response(status_code=204)


@router.websocket("/vnc")
async def host_vnc(websocket: WebSocket) -> None:
    """noVNC connects here. Bytes are forwarded to the host VNC server."""
    display = websocket.app.state.display
    port = getattr(display, "vnc_port", None)
    if not port:
        await websocket.close(code=1011)
        return
    await proxy_vnc(websocket, "127.0.0.1", port)
