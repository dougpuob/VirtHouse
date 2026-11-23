"""Host capacity check before a VM is started."""

from __future__ import annotations

import os
from pathlib import Path

from virthouse.config.models import SystemConfig
from virthouse.vm.errors import VmError
from virthouse.vm.models import VmSpec


def read_host_resources(meminfo: Path = Path("/proc/meminfo")) -> tuple[int, int]:
    """Return `(available_memory_mb, cpu_count)` from the host."""
    available_kb = None
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            available_kb = int(line.split()[1])
            break
    if available_kb is None:
        raise VmError("MemAvailable not found in /proc/meminfo")
    return available_kb // 1024, os.cpu_count() or 1


def ensure_capacity(
    spec: VmSpec,
    config: SystemConfig,
    *,
    host_memory_mb: int,
    host_cpus: int,
    used_memory_mb: int,
    used_cpus: int,
) -> None:
    """Reject a spec that exceeds the host reserve or the per-VM ceiling."""
    ceiling_memory = config.resources.max_vm_memory_mb
    ceiling_cpus = config.resources.max_vm_cpus
    if ceiling_memory and spec.memory_mb > ceiling_memory:
        raise VmError(
            f"memory exceeds ceiling (need {spec.memory_mb}MB, ceiling {ceiling_memory}MB)"
        )
    if ceiling_cpus and spec.cpus > ceiling_cpus:
        raise VmError(f"cpu exceeds ceiling (need {spec.cpus}, ceiling {ceiling_cpus})")

    available_memory = host_memory_mb - config.resources.reserve_memory_mb - used_memory_mb
    available_cpus = host_cpus - config.resources.reserve_cpus - used_cpus
    if spec.memory_mb > available_memory:
        raise VmError(
            f"memory insufficient (need {spec.memory_mb}MB, available {available_memory}MB)"
        )
    if spec.cpus > available_cpus:
        raise VmError(f"cpu insufficient (need {spec.cpus}, available {available_cpus})")
