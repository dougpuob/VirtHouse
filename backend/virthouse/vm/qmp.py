"""Minimal QMP client. Used to read query-status and a resource snapshot."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from virthouse.vm.models import QmpBlock, QmpCpu, QmpView

_MB = 1024 * 1024


async def query_status(socket_path: Path, timeout: float = 2.0) -> str:
    """Return the QEMU status string, for example `running`."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(str(socket_path)),
        timeout=timeout,
    )
    try:
        await asyncio.wait_for(reader.readline(), timeout=timeout)
        await _execute(reader, writer, "qmp_capabilities", timeout)
        payload = await _execute(reader, writer, "query-status", timeout)
    finally:
        writer.close()
        await writer.wait_closed()
    return str(payload["status"])


async def snapshot(socket_path: Path, timeout: float = 2.0) -> QmpView:
    """Read CPU, memory, and disk figures QEMU reports for one VM."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(str(socket_path)),
        timeout=timeout,
    )
    try:
        await asyncio.wait_for(reader.readline(), timeout=timeout)
        await _execute(reader, writer, "qmp_capabilities", timeout)
        status = await _execute(reader, writer, "query-status", timeout)
        cpus = await _execute(reader, writer, "query-cpus-fast", timeout)
        memory = await _execute(reader, writer, "query-memory-size-summary", timeout)
        blocks = await _execute(reader, writer, "query-block", timeout)
        stats = await _execute(reader, writer, "query-blockstats", timeout)
        kvm = await _execute(reader, writer, "query-kvm", timeout)
        version = await _execute(reader, writer, "query-version", timeout)
    finally:
        writer.close()
        await writer.wait_closed()
    return assemble_snapshot(status, cpus, memory, blocks, stats, kvm, version)


def assemble_snapshot(
    status: dict[str, Any],
    cpus: list[dict[str, Any]],
    memory: dict[str, Any],
    blocks: list[dict[str, Any]],
    stats: list[dict[str, Any]],
    kvm: dict[str, Any],
    version: dict[str, Any],
) -> QmpView:
    """Turn raw QMP replies into the figures shown on the VM panel."""
    qemu = version.get("qemu") or {}
    by_device = {item.get("device"): item for item in stats}
    disks: list[QmpBlock] = []
    for block in blocks:
        inserted = block.get("inserted") or {}
        image = inserted.get("image") or {}
        virtual = image.get("virtual-size")
        if not inserted.get("drv") and virtual is None:
            continue
        device = str(block.get("device") or "")
        counters = (by_device.get(device) or {}).get("stats") or {}
        disks.append(
            QmpBlock(
                device=device,
                driver=inserted.get("drv"),
                virtual_mb=None if virtual is None else int(virtual) // _MB,
                read_mb=int(counters.get("rd_bytes") or 0) // _MB,
                written_mb=int(counters.get("wr_bytes") or 0) // _MB,
            )
        )
    cpu_rows = [
        QmpCpu(
            index=int(cpu["cpu-index"]),
            thread_id=int(cpu["thread-id"]),
            core_id=(cpu.get("props") or {}).get("core-id"),
        )
        for cpu in cpus
    ]
    return QmpView(
        status=str(status.get("status") or ""),
        running=bool(status.get("running")),
        kvm=bool(kvm.get("enabled")),
        qemu_version=".".join(
            str(qemu.get(part, 0)) for part in ("major", "minor", "micro")
        ),
        cpu_count=len(cpu_rows),
        cpus=cpu_rows,
        memory_base_mb=int(memory.get("base-memory") or 0) // _MB,
        memory_plugged_mb=int(memory.get("plugged-memory") or 0) // _MB,
        blocks=disks,
    )


def parse_console_line(line: str) -> tuple[str, dict[str, Any] | None]:
    """Map one console line to a QMP command and its arguments.

    A JSON object is sent as itself. Anything else is a QEMU monitor line,
    forwarded with human-monitor-command.
    """
    text = line.strip()
    if not text:
        raise ValueError("empty command")
    if text.startswith("{"):
        message = json.loads(text)
        if not isinstance(message, dict) or "execute" not in message:
            raise ValueError("QMP command needs an execute field")
        arguments = message.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("QMP arguments must be an object")
        return str(message["execute"]), arguments
    return "human-monitor-command", {"command-line": text}


async def guest_agent_up(socket_path: Path, timeout: float = 0.4) -> bool:
    """Return whether qemu-ga answers guest-ping on this socket."""
    if not socket_path.exists():
        return False
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(socket_path)),
            timeout=timeout,
        )
    except (OSError, TimeoutError):
        return False
    try:
        await asyncio.wait_for(reader.readline(), timeout=timeout)
        await _execute(reader, writer, "qmp_capabilities", timeout)
        await _execute(reader, writer, "guest-ping", timeout)
    except (OSError, TimeoutError, ConnectionError, RuntimeError, json.JSONDecodeError):
        return False
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
    return True


async def execute(socket_path: Path, line: str, timeout: float = 8.0) -> str:
    """Run one console line against a QMP socket and return the text to show."""
    command, arguments = parse_console_line(line)
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(str(socket_path)),
        timeout=timeout,
    )
    try:
        await asyncio.wait_for(reader.readline(), timeout=timeout)
        await _execute(reader, writer, "qmp_capabilities", timeout)
        payload = await _execute(reader, writer, command, timeout, arguments)
    finally:
        writer.close()
        await writer.wait_closed()
    if command == "human-monitor-command":
        return str(payload or "")
    return json.dumps(payload, indent=2)


async def _execute(
    reader,
    writer,
    command: str,
    timeout: float,
    arguments: dict[str, Any] | None = None,
) -> Any:
    message: dict[str, Any] = {"execute": command}
    if arguments:
        message["arguments"] = arguments
    writer.write(json.dumps(message).encode() + b"\n")
    await writer.drain()
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not line:
            raise ConnectionError(f"QMP closed during {command}")
        reply = json.loads(line)
        if "return" in reply:
            return reply["return"]
        if "error" in reply:
            error = reply["error"]
            desc = error.get("desc") if isinstance(error, dict) else None
            raise RuntimeError(desc or str(error))
