"""VM API (DESIGN_v4.md section 11 — VM)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, WebSocket

from virthouse.api.deps import get_vms
from virthouse.vm.errors import VmNotFound
from virthouse.vm.manager import VmManager
from virthouse.vm.models import QmpCommand, QmpCommandResult, QmpView, RuntimeRecord, VmSpec, VmStatusView
from virthouse.vm.vnc import proxy_vnc

router = APIRouter(prefix="/vms", tags=["vms"])


@router.post("", response_model=RuntimeRecord, status_code=201)
async def start_vm(spec: VmSpec, manager: VmManager = Depends(get_vms)) -> RuntimeRecord:
    return await manager.start(spec)


@router.get("", response_model=list[RuntimeRecord])
async def list_vms(manager: VmManager = Depends(get_vms)) -> list[RuntimeRecord]:
    return manager.list()


@router.get("/{vm_id}", response_model=RuntimeRecord)
async def get_vm(vm_id: str, manager: VmManager = Depends(get_vms)) -> RuntimeRecord:
    return manager.get(vm_id)


@router.get("/{vm_id}/qmp", response_model=QmpView)
async def get_vm_qmp(vm_id: str, manager: VmManager = Depends(get_vms)) -> QmpView:
    """Return CPU, memory, and disk figures reported by this VM's QEMU."""
    return await manager.qmp_view(vm_id)


@router.post("/{vm_id}/qmp/execute", response_model=QmpCommandResult)
async def execute_qmp(
    vm_id: str,
    body: QmpCommand,
    manager: VmManager = Depends(get_vms),
) -> QmpCommandResult:
    """Run one QEMU monitor line, or one JSON QMP command, on this VM."""
    return await manager.qmp_execute(vm_id, body.command)


@router.get("/{vm_id}/status", response_model=VmStatusView)
async def get_vm_status(vm_id: str, manager: VmManager = Depends(get_vms)) -> VmStatusView:
    return manager.status(vm_id)


@router.post("/{vm_id}/reset", response_model=RuntimeRecord)
async def reset_vm(vm_id: str, manager: VmManager = Depends(get_vms)) -> RuntimeRecord:
    return await manager.reset(vm_id)


@router.delete("/{vm_id}", status_code=204)
async def delete_vm(vm_id: str, manager: VmManager = Depends(get_vms)) -> Response:
    await manager.delete(vm_id)
    return Response(status_code=204)


@router.websocket("/{vm_id}/vnc")
async def vnc_socket(websocket: WebSocket, vm_id: str) -> None:
    """noVNC connects here. Bytes are forwarded to the VM's VNC port."""
    manager: VmManager = websocket.app.state.vms
    try:
        record = manager.get(vm_id)
    except VmNotFound:
        await websocket.close(code=1008)
        return
    if record.vnc_port is None or record.status not in {"booting", "ready"}:
        await websocket.close(code=1008)
        return
    await proxy_vnc(websocket, "127.0.0.1", record.vnc_port)
