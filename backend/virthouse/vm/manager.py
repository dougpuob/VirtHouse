"""Start, stop, reset, and watch QEMU VMs in this backend process."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import uuid
from pathlib import Path

from virthouse.config.models import SystemConfig
from virthouse.history.store import HistoryStore
from virthouse.vm import overlay as overlay_mod
from virthouse.vm import process as process_mod
from virthouse.vm import qmp as qmp_mod
from virthouse.vm.errors import VmError, VmNotFound
from virthouse.vm.models import QmpCommandResult, QmpView, RuntimeRecord, VmSpec, VmStatusView
from virthouse.vm.network import assign_subnet, next_ordinal
from virthouse.vm.resources import HostResources, ensure_capacity, read_host_resources, read_host_view

logger = logging.getLogger(__name__)

_VNC_BASE = 5900


def _success_message(action: str, record: RuntimeRecord, spec: VmSpec) -> str:
    if action == "vm.reset":
        return f"Reset {record.name}. Started again from {spec.base_image}."
    return (
        f"Started {record.name} from {spec.base_image} "
        f"with {spec.cpus} CPU and {spec.memory_mb} MB."
    )


def _failure_message(action: str, exc: Exception) -> str:
    if action == "vm.reset":
        return f"Reset failed: {exc}"
    return f"Start failed: {exc}"
_ACTIVE = {"pending", "starting", "booting", "ready"}


class VmManager:
    def __init__(self, config: SystemConfig, history: HistoryStore | None = None) -> None:
        self._config = config
        self._history = history
        self._records: dict[str, RuntimeRecord] = {}
        self._specs: dict[str, VmSpec] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._generations: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._qmp_locks: dict[str, asyncio.Lock] = {}

    def live_subjects(self) -> list[tuple[str, str, int]]:
        """VMs still in this process, with the generation of their current boot."""
        return [
            ("vm", record.id, self._generations.get(record.id, 0))
            for record in self._records.values()
        ]

    def list(self) -> list[RuntimeRecord]:
        return list(self._records.values())

    def get(self, vm_id: str) -> RuntimeRecord:
        try:
            return self._records[vm_id]
        except KeyError as exc:
            raise VmNotFound(f"vm not found: {vm_id}") from exc

    def host_view(self) -> HostResources:
        processes = [("virthouse", os.getpid())]
        processes.extend(
            (record.name, record.pid)
            for record in self._records.values()
            if record.pid and record.status in _ACTIVE
        )
        return read_host_view(self._config, processes)

    async def qmp_view(self, vm_id: str) -> QmpView:
        record = self.get(vm_id)
        if record.qmp_socket is None:
            raise VmError("qmp socket is not open")
        async with self._qmp_lock(vm_id):
            try:
                view = await qmp_mod.snapshot(Path(record.qmp_socket))
            except (OSError, TimeoutError, ConnectionError, RuntimeError, asyncio.TimeoutError) as exc:
                raise VmError(f"qmp query failed: {exc}") from exc
        if record.qga_socket:
            view.guest_agent = await qmp_mod.guest_agent_up(Path(record.qga_socket))
        return view

    async def qmp_execute(self, vm_id: str, line: str) -> QmpCommandResult:
        record = self.get(vm_id)
        if record.qmp_socket is None or record.status not in {"booting", "ready"}:
            raise VmError("qmp socket is not open")
        async with self._qmp_lock(vm_id):
            try:
                output = await qmp_mod.execute(Path(record.qmp_socket), line)
            except (OSError, TimeoutError, ConnectionError, RuntimeError, asyncio.TimeoutError, ValueError, json.JSONDecodeError) as exc:
                raise VmError(str(exc)) from exc
        return QmpCommandResult(output=output)

    def _next_generation(self, vm_id: str) -> int:
        generation = self._generations.get(vm_id, 0) + 1
        self._generations[vm_id] = generation
        return generation

    def _note(
        self,
        *,
        level: str,
        action: str,
        subject_kind: str,
        message: str,
        subject_id: str | None = None,
        subject_name: str | None = None,
        generation: int = 0,
        detail: dict[str, object] | None = None,
    ) -> None:
        if self._history is None:
            return
        try:
            self._history.record(
                level=level,
                action=action,
                subject_kind=subject_kind,
                message=message,
                subject_id=subject_id,
                subject_name=subject_name,
                generation=generation,
                detail=detail,
            )
        except Exception:
            logger.exception("history record failed")

    def _qmp_lock(self, vm_id: str) -> asyncio.Lock:
        lock = self._qmp_locks.get(vm_id)
        if lock is None:
            lock = asyncio.Lock()
            self._qmp_locks[vm_id] = lock
        return lock

    def status(self, vm_id: str) -> VmStatusView:
        record = self.get(vm_id)
        return VmStatusView(
            id=record.id,
            status=record.status,
            ready=record.status == "ready",
            error=record.error,
        )

    async def start(self, spec: VmSpec) -> RuntimeRecord:
        try:
            self._reject_unsupported(spec)
            async with self._lock:
                self._ensure_capacity(spec)
                base = self._resolve_base(spec.base_image)
                record = self._new_record(spec)
                self._records[record.id] = record
                self._specs[record.id] = spec
        except VmError as exc:
            self._note(
                level="error",
                action="vm.start",
                subject_kind="vm",
                subject_name=spec.name,
                message=str(exc),
                detail={"base_image": spec.base_image, "cpus": spec.cpus, "memory_mb": spec.memory_mb},
            )
            raise
        try:
            await self._boot(record, spec, base, action="vm.start")
        except Exception as exc:
            logger.exception("start vm %s failed", record.id)
            await self._discard(record)
            raise VmError(str(exc)) from exc
        return record

    async def delete(self, vm_id: str) -> None:
        record = self.get(vm_id)
        logger.info("delete vm %s", vm_id)
        self._note(
            level="information",
            action="vm.delete",
            subject_kind="vm",
            subject_id=record.id,
            subject_name=record.name,
            generation=self._generations.get(record.id, 0),
            message=f"Stopped {record.name} and deleted its overlay.",
            detail={"overlay": record.overlay},
        )
        await self._stop_task(vm_id)
        await self._stop_process(record)
        self._delete_files(record)
        self._records.pop(vm_id, None)
        self._specs.pop(vm_id, None)
        self._generations.pop(vm_id, None)

    async def reset(self, vm_id: str) -> RuntimeRecord:
        record = self.get(vm_id)
        spec = self._specs[vm_id]
        base = self._resolve_base(spec.base_image)
        logger.info("reset vm %s", vm_id)
        await self._stop_task(vm_id)
        await self._stop_process(record)
        self._delete_files(record)
        record.error = None
        record.pid = None
        try:
            await self._boot(record, spec, base, action="vm.reset")
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            raise VmError(str(exc)) from exc
        return record

    async def shutdown(self) -> None:
        for vm_id in list(self._records):
            await self.delete(vm_id)

    async def _boot(self, record: RuntimeRecord, spec: VmSpec, base: Path, *, action: str) -> None:
        record.status = "starting"
        generation = self._next_generation(record.id)
        logger.info("%s vm %s name=%s base=%s", action, record.id, spec.name, spec.base_image)
        overlay = Path(record.overlay or "")
        qmp_socket = Path(record.qmp_socket or "")
        try:
            overlay_mod.create_overlay(base, overlay)
            qmp_socket.parent.mkdir(parents=True, exist_ok=True)
            proc = process_mod.spawn(
                process_mod.qemu_argv(
                    self._config.qemu.binary,
                    record,
                    spec.extra_qemu_args,
                    kvm=Path("/dev/kvm").exists(),
                ),
                qmp_socket.with_suffix(".log"),
            )
            self._procs[record.id] = proc
            record.pid = proc.pid
        except Exception as exc:
            self._note(
                level="error",
                action=action,
                subject_kind="vm",
                subject_id=record.id,
                subject_name=record.name,
                generation=generation,
                message=_failure_message(action, exc),
                detail={"error": str(exc)},
            )
            await self._stop_process(record)
            self._delete_files(record)
            raise
        self._note(
            level="information",
            action=action,
            subject_kind="vm",
            subject_id=record.id,
            subject_name=record.name,
            generation=generation,
            message=_success_message(action, record, spec),
            detail={
                "base_image": spec.base_image,
                "cpus": spec.cpus,
                "memory_mb": spec.memory_mb,
                "overlay": record.overlay,
                "guest_ip": record.guest_ip,
            },
        )
        record.status = "booting"
        self._tasks[record.id] = asyncio.create_task(self._watch(record))

    def _new_record(self, spec: VmSpec) -> RuntimeRecord:
        vm_id = uuid.uuid4().hex[:12]
        ordinal = next_ordinal(
            self._config.network.subnet_base,
            {record.subnet for record in self._records.values() if record.subnet},
        )
        subnet, gateway, guest_ip = assign_subnet(self._config.network.subnet_base, ordinal)
        return RuntimeRecord(
            id=vm_id,
            name=spec.name,
            status="pending",
            base_image=spec.base_image,
            cpus=spec.cpus,
            memory_mb=spec.memory_mb,
            overlay=str(Path(self._config.paths.overlays) / f"{vm_id}.qcow2"),
            qmp_socket=str(Path(self._config.paths.qmp) / f"{vm_id}.sock"),
            qga_socket=str(Path(self._config.paths.qmp) / f"{vm_id}.qga.sock"),
            vnc_port=self._next_vnc_port(),
            subnet=subnet,
            gateway=gateway,
            guest_ip=guest_ip,
        )

    def _reject_unsupported(self, spec: VmSpec) -> None:
        if spec.passthrough:
            raise VmError("passthrough is not implemented")
        if spec.ready_check != "basic":
            raise VmError(f"ready check {spec.ready_check!r} is not implemented")

    def _ensure_capacity(self, spec: VmSpec) -> None:
        active = [record for record in self._records.values() if record.status in _ACTIVE]
        host_memory, host_cpus = read_host_resources()
        ensure_capacity(
            spec,
            self._config,
            host_memory_mb=host_memory,
            host_cpus=host_cpus,
            used_memory_mb=sum(record.memory_mb for record in active),
            used_cpus=sum(record.cpus for record in active),
        )

    def _resolve_base(self, base_image: str) -> Path:
        if Path(base_image).name != base_image or base_image in {"", ".", ".."}:
            raise VmError(f"base image not found: {base_image}")
        root = Path(self._config.paths.bases).resolve()
        candidate = (root / base_image).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise VmError(f"base image not found: {base_image}")
        return candidate

    def _next_vnc_port(self) -> int:
        used = {record.vnc_port for record in self._records.values() if record.vnc_port}
        port = _VNC_BASE
        while port in used:
            port += 1
        return port

    async def _watch(self, record: RuntimeRecord) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        limit = self._config.timeouts.basic_ready_sec
        spec = self._specs.get(record.id)
        if spec is not None and spec.ready_timeout_sec is not None:
            limit = spec.ready_timeout_sec
        try:
            while True:
                proc = self._procs.get(record.id)
                if proc is None or proc.poll() is not None:
                    record.status = "failed"
                    record.error = "qemu process exited"
                    code = None if proc is None else proc.returncode
                    logger.info("vm %s qemu exited", record.id)
                    self._note(
                        level="error",
                        action="vm.exit",
                        subject_kind="vm",
                        subject_id=record.id,
                        subject_name=record.name,
                        generation=self._generations.get(record.id, 0),
                        message=f"QEMU exited before the guest was ready. Exit code {code}.",
                        detail={"exit_code": code},
                    )
                    return
                if await self._basic_ready(record):
                    record.status = "ready"
                    record.error = None
                    logger.info("vm %s ready", record.id)
                    where = f" at {record.guest_ip}" if record.guest_ip else ""
                    self._note(
                        level="information",
                        action="vm.ready",
                        subject_kind="vm",
                        subject_id=record.id,
                        subject_name=record.name,
                        generation=self._generations.get(record.id, 0),
                        message=f"Guest is ready{where}.",
                        detail={"guest_ip": record.guest_ip, "vnc_port": record.vnc_port},
                    )
                    return
                if loop.time() - started > limit:
                    await self._mark_timeout(record)
                    return
                await asyncio.sleep(0.5 if loop.time() - started < 10 else 2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            logger.exception("watch vm %s failed", record.id)
            self._note(
                level="error",
                action="vm.exit",
                subject_kind="vm",
                subject_id=record.id,
                subject_name=record.name,
                generation=self._generations.get(record.id, 0),
                message=f"Watch failed: {exc}",
                detail={"error": str(exc)},
            )

    async def _basic_ready(self, record: RuntimeRecord) -> bool:
        if record.qmp_socket is None or record.vnc_port is None:
            return False
        try:
            status = await qmp_mod.query_status(Path(record.qmp_socket))
        except (OSError, TimeoutError, ConnectionError, RuntimeError, asyncio.TimeoutError):
            return False
        if status != "running":
            return False
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", record.vnc_port),
                timeout=1,
            )
        except (OSError, TimeoutError, asyncio.TimeoutError):
            return False
        writer.close()
        await writer.wait_closed()
        return True

    async def _mark_timeout(self, record: RuntimeRecord) -> None:
        logger.info("vm %s basic ready timeout", record.id)
        self._note(
            level="error",
            action="vm.start",
            subject_kind="vm",
            subject_id=record.id,
            subject_name=record.name,
            generation=self._generations.get(record.id, 0),
            message="Start failed: basic ready timed out.",
        )
        await self._stop_process(record)
        self._delete_files(record)
        record.status = "timeout"
        record.error = "basic ready timeout"
        record.pid = None

    async def _discard(self, record: RuntimeRecord) -> None:
        await self._stop_task(record.id)
        await self._stop_process(record)
        self._delete_files(record)
        self._records.pop(record.id, None)
        self._specs.pop(record.id, None)

    async def _stop_task(self, vm_id: str) -> None:
        task = self._tasks.pop(vm_id, None)
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _stop_process(self, record: RuntimeRecord) -> None:
        proc = self._procs.pop(record.id, None)
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.to_thread(proc.wait, 5)
            except subprocess.TimeoutExpired:
                proc.kill()
                await asyncio.to_thread(proc.wait)
        record.pid = None

    def _delete_files(self, record: RuntimeRecord) -> None:
        if record.overlay:
            overlay_mod.delete_overlay(Path(record.overlay))
        if record.qmp_socket:
            socket_path = Path(record.qmp_socket)
            if socket_path.exists():
                socket_path.unlink()
            log_path = socket_path.with_suffix(".log")
            if log_path.is_file():
                log_path.unlink()
        if record.qga_socket:
            qga_path = Path(record.qga_socket)
            if qga_path.exists():
                qga_path.unlink()
        self._qmp_locks.pop(record.id, None)
