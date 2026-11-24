"""Bridge a browser WebSocket to a VM's VNC TCP port.

noVNC speaks the raw RFB protocol over a WebSocket. QEMU listens for RFB on
TCP. This copies bytes both ways.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def proxy_vnc(websocket: WebSocket, host: str, port: int) -> None:
    """Accept the WebSocket and connect it to `host:port`."""
    await websocket.accept()
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError as exc:
        logger.info("VNC connect %s:%s failed: %s", host, port, exc)
        await websocket.close(code=1011)
        return

    logger.info("VNC proxy connected to %s:%s", host, port)
    async def vnc_to_browser() -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await websocket.send_bytes(data)
        except (WebSocketDisconnect, RuntimeError):
            return

    async def browser_to_vnc() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data is None and message.get("text") is not None:
                    data = message["text"].encode("latin-1")
                if not data:
                    continue
                writer.write(data)
                await writer.drain()
        except WebSocketDisconnect:
            return

    tasks = {
        asyncio.create_task(vnc_to_browser()),
        asyncio.create_task(browser_to_vnc()),
    }
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    except Exception:
        logger.exception("VNC proxy to %s:%s failed", host, port)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        logger.info("VNC proxy closed %s:%s", host, port)
