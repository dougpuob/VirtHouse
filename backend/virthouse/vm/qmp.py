"""Minimal QMP client. Used to read query-status for basic readiness."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path


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


async def _execute(reader, writer, command: str, timeout: float) -> dict:
    writer.write(json.dumps({"execute": command}).encode() + b"\n")
    await writer.drain()
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not line:
            raise ConnectionError(f"QMP closed during {command}")
        message = json.loads(line)
        if "return" in message:
            return message["return"]
        if "error" in message:
            raise RuntimeError(message["error"])
