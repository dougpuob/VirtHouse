"""VNC server for this computer's desktop.

noVNC speaks RFB. This listens on localhost, sends the desktop as Tight JPEG
rectangles, and turns pointer and key events into desktop input.
"""

from __future__ import annotations

import logging
import select
import socket
import struct
import threading
import time

logger = logging.getLogger(__name__)

TIGHT = 7
DESKTOP_SIZE = -223
_WHEEL = {3: (0.0, -120.0), 4: (0.0, 120.0), 5: (-120.0, 0.0), 6: (120.0, 0.0)}


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Read the width and height from a JPEG SOF marker."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 8 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            if width > 0 and height > 0:
                return width, height
            return None
        if marker == 0x01 or marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if index + 4 > len(data):
            return None
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if length < 2:
            return None
        index += 2 + length
    return None


def _compact_length(length: int) -> bytes:
    if length < 128:
        return bytes((length,))
    if length < 16384:
        return bytes((length & 0x7F | 0x80, (length >> 7) & 0x7F))
    return bytes((length & 0x7F | 0x80, (length >> 7) & 0x7F | 0x80, (length >> 14) & 0xFF))


def tight_jpeg_rect(jpeg: bytes, width: int, height: int) -> bytes:
    """One FramebufferUpdate whose rectangle is the JPEG in Tight encoding."""
    header = struct.pack("!BBHHHHHi", 0, 0, 1, 0, 0, width, height, TIGHT)
    return header + bytes((0x90,)) + _compact_length(len(jpeg)) + jpeg


def desktop_size_rect(width: int, height: int) -> bytes:
    return struct.pack("!BBHHHHHi", 0, 0, 1, 0, 0, width, height, DESKTOP_SIZE)


def server_init(width: int, height: int, name: str = "VirtHouse host") -> bytes:
    encoded = name.encode()
    pixel = struct.pack("!BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
    return struct.pack("!HH", width, height) + pixel + struct.pack("!I", len(encoded)) + encoded


def _send_all(conn: socket.socket, data: bytes) -> None:
    conn.settimeout(5)
    conn.setblocking(True)
    conn.sendall(data)
    conn.setblocking(False)


def _read_exact(conn: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = conn.recv(remaining)
        if not chunk:
            raise ConnectionError("VNC client closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _handshake(conn: socket.socket, width: int, height: int) -> None:
    conn.sendall(b"RFB 003.008\n")
    version = _read_exact(conn, 12)
    if not version.startswith(b"RFB 003."):
        raise ConnectionError("unsupported RFB version")
    conn.sendall(bytes((1, 1)))
    chosen = _read_exact(conn, 1)
    if chosen != b"\x01":
        raise ConnectionError("client rejected security type None")
    conn.sendall(b"\x00\x00\x00\x00")
    _read_exact(conn, 1)
    conn.sendall(server_init(width, height))


def _apply_pointer(display, mask: int, x: int, y: int, previous: int) -> None:
    display.send({"op": "move", "x": x, "y": y})
    for bit, (dx, dy) in _WHEEL.items():
        flag = 1 << bit
        if mask & flag and not previous & flag:
            display.send({"op": "wheel", "dx": dx, "dy": dy})
    buttons = mask & 0x07
    old = previous & 0x07
    for button, bit in ((1, 0x01), (2, 0x02), (3, 0x04)):
        if buttons & bit and not old & bit:
            display.send({"op": "button", "button": button, "down": True})
        elif old & bit and not buttons & bit:
            display.send({"op": "button", "button": button, "down": False})


def _take_message(buf: bytearray):
    """Pop one complete client message, or return None when more bytes are needed."""
    if not buf:
        return None
    kind = buf[0]
    if kind == 0:
        need = 20
        if len(buf) < need:
            return None
        del buf[:need]
        return ("format",)
    if kind == 2:
        if len(buf) < 4:
            return None
        count = int.from_bytes(buf[2:4], "big")
        need = 4 + count * 4
        if len(buf) < need:
            return None
        encodings = [struct.unpack_from("!i", buf, 4 + index * 4)[0] for index in range(count)]
        del buf[:need]
        return ("encodings", encodings)
    if kind == 3:
        if len(buf) < 10:
            return None
        incremental, x, y, width, height = struct.unpack_from("!BHHHH", buf, 1)
        del buf[:10]
        return ("update", incremental, x, y, width, height)
    if kind == 4:
        if len(buf) < 8:
            return None
        down, keysym = struct.unpack_from("!BxxI", buf, 1)
        del buf[:8]
        return ("key", down, keysym)
    if kind == 5:
        if len(buf) < 6:
            return None
        mask, x, y = struct.unpack_from("!BHH", buf, 1)
        del buf[:6]
        return ("pointer", mask, x, y)
    if kind == 6:
        if len(buf) < 8:
            return None
        length = struct.unpack_from("!i", buf, 4)[0]
        payload = abs(length)
        if payload > 8_000_000:
            raise ConnectionError("clipboard message is too large")
        if len(buf) < 8 + payload:
            return None
        del buf[: 8 + payload]
        return ("cut",)
    raise ConnectionError(f"unknown client message {kind}")


def serve_client(conn: socket.socket, display, stop: threading.Event) -> None:
    """Speak RFB with one client until it disconnects."""
    jpeg = _wait_frame(display, stop)
    if jpeg is None:
        return
    size = jpeg_size(jpeg)
    if size is None:
        return
    width, height = size
    _handshake(conn, width, height)
    conn.setblocking(False)
    pending = False
    incremental = True
    sent = b""
    mask = 0
    buf = bytearray()
    while not stop.is_set():
        readable, _, _ = select.select([conn], [], [], 0.05)
        if readable:
            try:
                chunk = conn.recv(65536)
            except BlockingIOError:
                chunk = b""
            if not chunk:
                return
            buf += chunk
            while True:
                message = _take_message(buf)
                if message is None:
                    break
                kind = message[0]
                if kind == "update":
                    pending = True
                    incremental = bool(message[1])
                elif kind == "pointer":
                    _apply_pointer(display, message[1], message[2], message[3], mask)
                    mask = message[1]
                elif kind == "key":
                    display.send({"op": "key", "keysym": message[2], "down": bool(message[1])})
        latest = display.frame()
        if not pending or not latest:
            continue
        if incremental and latest == sent:
            continue
        latest_size = jpeg_size(latest)
        if latest_size is None:
            continue
        if latest_size != (width, height):
            width, height = latest_size
            _send_all(conn, desktop_size_rect(width, height))
        _send_all(conn, tight_jpeg_rect(latest, width, height))
        sent = latest
        pending = False


def _wait_frame(display, stop: threading.Event, timeout: float = 8.0) -> bytes | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not stop.is_set():
        frame = display.frame()
        if frame:
            return frame
        time.sleep(0.05)
    return None


class HostVnc:
    """Accept one localhost VNC client at a time."""

    def __init__(self, display) -> None:
        self._display = display
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self._sock.settimeout(0.5)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._accept, name="host-vnc", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2)

    def _accept(self) -> None:
        active: socket.socket | None = None
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            if addr[0] != "127.0.0.1":
                conn.close()
                continue
            if active is not None:
                try:
                    active.close()
                except OSError:
                    pass
            active = conn
            threading.Thread(target=self._client, args=(conn,), name="host-vnc-client", daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        conn.settimeout(10)
        try:
            serve_client(conn, self._display, self._stop)
        except (ConnectionError, OSError) as exc:
            logger.info("host VNC client ended: %s", exc)
        except Exception:
            logger.exception("host VNC client failed")
        finally:
            try:
                conn.close()
            except OSError:
                pass
