"""noVNC WebSocket proxy. A local TCP socket stands in for QEMU's VNC port."""

from __future__ import annotations

import socket
import threading

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from virthouse.config.loader import load_config
from virthouse.main import create_app
from virthouse.vm.errors import VmNotFound
from virthouse.vm.models import RuntimeRecord

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


class _Manager:
    def __init__(self, record: RuntimeRecord | None) -> None:
        self.record = record

    def get(self, vm_id: str) -> RuntimeRecord:
        if self.record is None or vm_id != self.record.id:
            raise VmNotFound(f"vm not found: {vm_id}")
        return self.record


def _record(port: int | None, status: str = "ready") -> RuntimeRecord:
    return RuntimeRecord(
        id="vm1",
        name="demo",
        status=status,
        base_image="base.qcow2",
        cpus=1,
        memory_mb=512,
        vnc_port=port,
    )


def _config():
    return load_config(REPO_ROOT / "config" / "system.yaml")


def _listen() -> tuple[socket.socket, int]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    return server, server.getsockname()[1]


def test_home_page_is_served() -> None:
    app = create_app(_config(), manager=_Manager(None))
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/ui/assets/app.js")
    assert page.status_code == 200
    assert script.status_code == 200
    text = page.text + script.text
    for label in (
        "Start Ubuntu 24.04",
        "Dashboard",
        "Machines",
        "Builder",
        "Resource",
        "History",
        "Creating",
        "Dump",
        "Settings",
        "Screen view",
        "Screen control",
        "Expand",
        "QMP",
        "images.yaml",
    ):
        assert label in text


def test_vnc_page_is_served() -> None:
    app = create_app(_config(), manager=_Manager(None))
    with TestClient(app) as client:
        page = client.get("/ui/vnc.html")
        script = client.get("/ui/novnc.js")
    assert page.status_code == 200
    assert "noVNC" in page.text
    assert script.status_code == 200
    assert "export default" in script.text


def test_vnc_rejects_unknown_vm() -> None:
    app = create_app(_config(), manager=_Manager(None))
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/api/v1/vms/missing/vnc"):
                pass
            raise AssertionError("websocket was accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008


def test_vnc_proxy_copies_bytes_both_ways() -> None:
    server, port = _listen()
    received: list[bytes] = []

    def serve() -> None:
        conn, _addr = server.accept()
        with conn:
            greeting = b"RFB 003.008\n"
            conn.sendall(greeting)
            data = conn.recv(64)
            received.append(data)
            conn.sendall(b"ok:" + data)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    app = create_app(_config(), manager=_Manager(_record(port)))
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/vms/vm1/vnc") as socket:
            assert socket.receive_bytes() == b"RFB 003.008\n"
            socket.send_bytes(b"hello")
            assert socket.receive_bytes() == b"ok:hello"
    assert received == [b"hello"]
