"""Host desktop window. The capture itself needs the GNOME session, so these tests stub it."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from virthouse.config.loader import load_config
from virthouse.host.capture import active_connectors
from virthouse.host.display import read_frames
from virthouse.host.input import keysym_for, normalize_input
from virthouse.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config():
    cfg = load_config(REPO_ROOT / "config" / "system.yaml")
    cfg.resources.reserve_memory_mb = 0
    cfg.resources.reserve_cpus = 0
    cfg.resources.max_vm_memory_mb = 0
    cfg.resources.max_vm_cpus = 0
    return cfg


class StubDisplay:
    def __init__(self, frame: bytes | None, problem: str = "") -> None:
        self._frame = frame
        self._problem = problem
        self.closed = False
        self.sent = []

    def frame(self) -> bytes | None:
        return self._frame

    def problem(self) -> str:
        return self._problem

    def close(self) -> None:
        self.closed = True

    def send(self, event: dict) -> None:
        self.sent.append(event)


def test_keys_and_buttons_become_desktop_commands() -> None:
    assert keysym_for("KeyA", "a") == ord("a")
    assert keysym_for("Enter", "Enter") == 0xFF0D
    assert keysym_for("F5", "F5") == 0xFFC2
    assert normalize_input({"op": "button", "button": 1, "down": True}) == {"op": "button", "button": 1, "down": True}
    assert normalize_input({"op": "button", "button": 9, "down": True}) is None
    assert normalize_input({"op": "key", "code": "Enter", "key": "Enter", "down": False})["keysym"] == 0xFF0D


def test_primary_connector_comes_first() -> None:
    logical = [
        (0, 0, 1.0, 0, False, [("DP-1", "A", "B", "C")]),
        (0, 0, 1.0, 0, True, [("HDMI-2", "LNX", "PiKVM", "CAFE")]),
    ]
    assert active_connectors(logical) == ["HDMI-2", "DP-1"]


def test_read_frames_splits_length_prefixed_jpegs() -> None:
    first = b"\xff\xd8one"
    second = b"\xff\xd8two"
    stream = BytesIO(len(first).to_bytes(4, "big") + first + len(second).to_bytes(4, "big") + second)
    found = []
    read_frames(stream, found.append)
    assert found == [first, second]


def test_screen_returns_the_jpeg_or_why_it_cannot() -> None:
    app = create_app(_config(), display=StubDisplay(b"\xff\xd8\xff"))
    with TestClient(app) as client:
        picture = client.get("/api/v1/resources/screen")
        assert picture.status_code == 200
        assert picture.headers["content-type"] == "image/jpeg"
        assert picture.content == b"\xff\xd8\xff"

    missing = create_app(_config(), display=StubDisplay(None, "No host display is connected."))
    with TestClient(missing) as client:
        response = client.get("/api/v1/resources/screen")
        assert response.status_code == 503
        assert response.json()["detail"] == "No host display is connected."


def _recv_exact(sock, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        assert chunk
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def test_host_vnc_pushes_a_frame_and_forwards_input() -> None:
    import socket
    import struct
    import time

    from virthouse.host.vnc import HostVnc, jpeg_size

    jpeg = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x02\x00\x03" + b"\x00" * 10
    assert jpeg_size(jpeg) == (3, 2)
    display = StubDisplay(jpeg)
    server = HostVnc(display)
    sock = None
    try:
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=2)
        sock.settimeout(2)
        assert _recv_exact(sock, 12) == b"RFB 003.008\n"
        sock.sendall(b"RFB 003.008\n")
        count = _recv_exact(sock, 1)[0]
        types = _recv_exact(sock, count)
        assert 1 in types
        sock.sendall(b"\x01")
        assert _recv_exact(sock, 4) == b"\x00\x00\x00\x00"
        sock.sendall(b"\x01")
        width, height = struct.unpack("!HH", _recv_exact(sock, 4))
        assert (width, height) == (3, 2)
        _recv_exact(sock, 16)
        name = _recv_exact(sock, struct.unpack("!I", _recv_exact(sock, 4))[0])
        assert name == b"VirtHouse host"
        sock.sendall(struct.pack("!BBH i", 2, 0, 1, 7))
        sock.sendall(struct.pack("!BBHHHH", 3, 0, 0, 0, 3, 2))
        header = _recv_exact(sock, 16)
        assert struct.unpack("!i", header[12:16])[0] == 7
        assert _recv_exact(sock, 1) == b"\x90"
        sock.sendall(struct.pack("!BBHH", 5, 1, 1, 0))
        sock.sendall(struct.pack("!BBxxI", 4, 1, 0xFFE1))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and len(display.sent) < 3:
            time.sleep(0.02)
    finally:
        server.close()
        if sock is not None:
            sock.close()
    assert {"op": "move", "x": 1, "y": 0} in display.sent
    assert {"op": "button", "button": 1, "down": True} in display.sent
    assert {"op": "key", "keysym": 0xFFE1, "down": True} in display.sent


def test_screen_input_is_forwarded() -> None:
    display = StubDisplay(b"\xff\xd8\xff")
    app = create_app(_config(), display=display)
    with TestClient(app) as client:
        response = client.post("/api/v1/resources/screen/input", json={"op": "button", "button": 1, "down": True})
        assert response.status_code == 204
        ignored = client.post("/api/v1/resources/screen/input", json={"op": "nope"})
        assert ignored.status_code == 204
    assert display.sent == [
        {"op": "button", "button": 1, "down": True},
        {"op": "nope"},
    ]
