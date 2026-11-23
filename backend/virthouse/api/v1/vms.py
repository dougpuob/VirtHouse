"""VM API (DESIGN_v4.md section 11 — VM)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from virthouse.api.deps import get_vms
from virthouse.vm.manager import VmManager
from virthouse.vm.models import RuntimeRecord, VmSpec, VmStatusView

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
