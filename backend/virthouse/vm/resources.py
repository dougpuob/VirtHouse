"""Host capacity check before a VM is started."""

from __future__ import annotations

import os
import socket
from pathlib import Path

from pydantic import BaseModel

from virthouse.config.models import SystemConfig
from virthouse.vm.errors import VmError
from virthouse.vm.models import VmSpec


class ProcessUsage(BaseModel):
    """One process on this host. RSS is resident memory, not the guest's -m."""

    name: str
    pid: int
    rss_mb: int
    threads: int | None = None


class HostResources(BaseModel):
    """This machine, as the host sees it. QMP does not report these numbers."""

    hostname: str
    cpu_count: int
    memory_total_mb: int
    memory_available_mb: int
    load_1m: float
    load_5m: float
    load_15m: float
    reserve_memory_mb: int
    reserve_cpus: int
    qemu_binary: str
    subnet_base: str
    processes: list[ProcessUsage]


def read_host_view(
    config: SystemConfig,
    processes: list[tuple[str, int]],
    *,
    meminfo: Path = Path("/proc/meminfo"),
    loadavg: Path = Path("/proc/loadavg"),
) -> HostResources:
    """Read host memory, CPU, load, and the resident size of named processes."""
    totals: dict[str, int] = {}
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:")):
            totals[line.split(":", 1)[0]] = int(line.split()[1])
    if "MemAvailable" not in totals or "MemTotal" not in totals:
        raise VmError("MemTotal or MemAvailable not found in /proc/meminfo")
    load = [float(part) for part in loadavg.read_text(encoding="utf-8").split()[:3]]
    return HostResources(
        hostname=socket.gethostname(),
        cpu_count=os.cpu_count() or 1,
        memory_total_mb=totals["MemTotal"] // 1024,
        memory_available_mb=totals["MemAvailable"] // 1024,
        load_1m=load[0],
        load_5m=load[1],
        load_15m=load[2],
        reserve_memory_mb=config.resources.reserve_memory_mb,
        reserve_cpus=config.resources.reserve_cpus,
        qemu_binary=config.qemu.binary,
        subnet_base=config.network.subnet_base,
        processes=[usage for usage in (_process_usage(name, pid) for name, pid in processes) if usage],
    )


def _process_usage(name: str, pid: int) -> ProcessUsage | None:
    status = Path(f"/proc/{pid}/status")
    if not status.is_file():
        return None
    rss_kb = None
    threads = None
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            rss_kb = int(line.split()[1])
        elif line.startswith("Threads:"):
            threads = int(line.split()[1])
    return ProcessUsage(name=name, pid=pid, rss_mb=(rss_kb or 0) // 1024, threads=threads)


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
