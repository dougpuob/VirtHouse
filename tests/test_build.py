"""Packer runs: the template hook, the storyboard, and the screenshots API."""

from __future__ import annotations

import socket
import struct
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from virthouse.build.errors import BuildError
from virthouse.build.runner import BuildRunner
from virthouse.build.screen import (
    Storyboard,
    consider_frame,
    instrument_hcl,
    ppm_to_png,
    step_label,
)
from virthouse.config.loader import load_config
from virthouse.main import create_app
from virthouse.vm.errors import VmNotFound
from virthouse.vm.models import RuntimeRecord

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = 'source "qemu" "image" {\n  iso_url = "disc.iso"\n}\n'


class _Manager:
    def get(self, vm_id: str) -> RuntimeRecord:
        raise VmNotFound(f"vm not found: {vm_id}")


def test_instrument_hcl_adds_vnc_and_qmp() -> None:
    text = instrument_hcl(SAMPLE, Path("/tmp/packer.qmp"), 5911)
    assert text.index("vnc_port_min") < text.index("iso_url")
    assert "vnc_port_min      = 5911" in text
    assert "vnc_port_max      = 5911" in text
    assert "127.0.0.1:11,share=force-shared" in text
    assert 'unix:/tmp/packer.qmp,server=on,wait=off' in text
    assert "bootindex" not in text


def test_instrument_hcl_boots_the_uefi_cd_first() -> None:
    hcl = 'source "qemu" "image" {\n  efi_boot = true\n  iso_url = "disc.iso"\n}\n'
    text = instrument_hcl(hcl, Path("/tmp/packer.qmp"), 5911)
    assert '[ "-global", "ide-cd.bootindex=0" ]' in text
    assert text.index("qemuargs") < text.index("efi_boot")


def test_step_label_strips_the_packer_prefix() -> None:
    assert step_label("==> qemu.image: Typing the boot command") == "Typing the boot command"


def test_ppm_to_png_writes_a_one_pixel_image() -> None:
    png = ppm_to_png(b"P6\n1 1\n255\n\xff\x00\x00")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert png[16:24] == struct.pack(">II", 1, 1)


def test_consider_frame_keeps_changes_and_skips_duplicates() -> None:
    board = Storyboard()
    assert consider_frame(board, b"a", "Typing", 0, keep_every=12, max_shots=80) is True
    assert consider_frame(board, b"a", "Waiting", 1, keep_every=12, max_shots=80) is False
    assert consider_frame(board, b"b", "Waiting", 2, keep_every=12, max_shots=80) is True
    assert consider_frame(board, b"c", "Waiting", 3, keep_every=12, max_shots=80) is False
    assert consider_frame(board, b"d", "Waiting", 20, keep_every=12, max_shots=80) is True
    assert board.frame == 5
    assert board.labels == ["Typing", "Waiting", "Waiting"]


def _script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _capture_factory():
    frames = {"n": 0}

    async def capture(_socket: Path, dest: Path) -> None:
        frames["n"] += 1
        dest.write_bytes(f"frame-{frames['n']}".encode())

    return capture


async def test_runner_keeps_a_screenshot_when_the_display_changes(tmp_path: Path) -> None:
    script = tmp_path / "fake-packer"
    _script(
        script,
        """#!/bin/sh
if [ "$1" = "init" ]; then
  exit 0
fi
file=""
for arg in "$@"; do
  case "$arg" in
    *.pkr.hcl) file=$arg ;;
  esac
done
qmp=$(sed -n 's/.*unix:\\([^,]*\\),server.*/\\1/p' "$file" | head -1)
touch "$qmp"
echo "qemu.image: Typing the boot command"
sleep 0.25
echo "qemu.image: Waiting for SSH to become available"
sleep 0.25
exit 0
""",
    )
    runner = BuildRunner(packer=str(script), capture=_capture_factory(), interval=0.05, keep_every=0)
    view = await runner.start(name="demo", hcl=SAMPLE, work=tmp_path / "work")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        view = runner.get(view.id)
        if view.status != "running":
            break
        await _asleep()
    assert view.status == "done"
    assert view.shots
    assert view.shots[0].label == "Typing the boot command"
    assert (tmp_path / "work" / ".runs" / view.id / "shots" / "0001.png").read_bytes().startswith(b"frame-")
    latest = runner.screen_path(view.id, "latest.png")
    assert latest is not None and latest.is_file()


async def test_cancel_stops_the_pack(tmp_path: Path) -> None:
    script = tmp_path / "fake-packer"
    _script(
        script,
        """#!/bin/sh
if [ "$1" = "init" ]; then
  exit 0
fi
sleep 30
""",
    )
    runner = BuildRunner(packer=str(script), capture=_capture_factory(), interval=0.05)
    view = await runner.start(name="demo", hcl=SAMPLE, work=tmp_path / "work")
    await _asleep()
    await runner.cancel(view.id)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        view = runner.get(view.id)
        if view.status != "running":
            break
        await _asleep()
    assert view.status == "cancelled"


async def test_refuses_a_second_pack_and_a_full_directory(tmp_path: Path) -> None:
    script = tmp_path / "fake-packer"
    _script(script, "#!/bin/sh\nif [ \"$1\" = init ]; then exit 0; fi\nsleep 30\n")
    runner = BuildRunner(packer=str(script), capture=_capture_factory(), interval=0.05)
    first = await runner.start(name="demo", hcl=SAMPLE, work=tmp_path / "work")
    with pytest.raises(BuildError, match="already running"):
        await runner.start(name="other", hcl=SAMPLE, work=tmp_path / "work")
    await runner.cancel(first.id)
    await runner.shutdown()
    full = tmp_path / "work" / "taken"
    full.mkdir()
    (full / "disk.qcow2").write_bytes(b"x")
    held = BuildRunner(packer=str(script), capture=_capture_factory())
    with pytest.raises(BuildError, match="not empty"):
        await held.start(name="taken", hcl=SAMPLE, work=tmp_path / "work")


def test_api_serves_the_screenshots(tmp_path: Path) -> None:
    script = tmp_path / "fake-packer"
    _script(
        script,
        """#!/bin/sh
if [ "$1" = "init" ]; then
  exit 0
fi
file=""
for arg in "$@"; do
  case "$arg" in
    *.pkr.hcl) file=$arg ;;
  esac
done
qmp=$(sed -n 's/.*unix:\\([^,]*\\),server.*/\\1/p' "$file" | head -1)
touch "$qmp"
echo "qemu.image: Typing the boot command"
sleep 0.2
exit 0
""",
    )
    cfg = load_config(REPO_ROOT / "config" / "system.yaml")
    cfg.paths.work = str(tmp_path / "work")
    cfg.paths.history = str(tmp_path / "history.db")
    runner = BuildRunner(packer=str(script), capture=_capture_factory(), interval=0.05, keep_every=0)
    app = create_app(cfg, manager=_Manager(), builds=runner)
    with TestClient(app) as client:
        created = client.post("/api/v1/builds", json={"name": "demo", "hcl": SAMPLE})
        assert created.status_code == 201
        run_id = created.json()["id"]
        deadline = time.monotonic() + 5
        body = created.json()
        while time.monotonic() < deadline and body["status"] == "running":
            time.sleep(0.05)
            body = client.get(f"/api/v1/builds/{run_id}").json()
        assert body["status"] == "done"
        assert body["vnc_port"] is None
        assert body["shots"]
        keys = client.post(f"/api/v1/builds/{run_id}/keys", json={"key": "ret"})
        assert keys.status_code == 404
        shot = client.get(f"/api/v1/builds/{run_id}/screen/{body['shots'][0]['id']}.png")
        assert shot.status_code == 200
        assert shot.content.startswith(b"frame-")
        missing = client.get(f"/api/v1/builds/{run_id}/screen/not-a-shot.png")
        assert missing.status_code == 404


def test_build_vnc_rejects_unknown_pack(tmp_path: Path) -> None:
    app = _app(tmp_path, BuildRunner(packer="false"))
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/api/v1/builds/missing/vnc"):
                pass
            raise AssertionError("websocket was accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008


def test_build_vnc_waits_until_the_display_is_up(tmp_path: Path) -> None:
    script = tmp_path / "fake-packer"
    _script(script, "#!/bin/sh\nif [ \"$1\" = init ]; then exit 0; fi\nsleep 30\n")
    app = _app(tmp_path, BuildRunner(packer=str(script), capture=_capture_factory(), interval=0.05))
    with TestClient(app) as client:
        created = client.post("/api/v1/builds", json={"name": "demo", "hcl": SAMPLE})
        assert created.status_code == 201
        run_id = created.json()["id"]
        assert created.json()["vnc_port"] is None
        try:
            with client.websocket_connect(f"/api/v1/builds/{run_id}/vnc"):
                pass
            raise AssertionError("websocket was accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008


def test_build_vnc_proxy_copies_bytes_both_ways(tmp_path: Path) -> None:
    script = tmp_path / "fake-packer"
    _script(
        script,
        """#!/bin/sh
if [ "$1" = "init" ]; then
  exit 0
fi
file=""
for arg in "$@"; do
  case "$arg" in
    *.pkr.hcl) file=$arg ;;
  esac
done
qmp=$(sed -n 's/.*unix:\\([^,]*\\),server.*/\\1/p' "$file" | head -1)
touch "$qmp"
echo "qemu.image: Typing the boot command"
sleep 30
""",
    )
    app = _app(tmp_path, BuildRunner(packer=str(script), capture=_capture_factory(), interval=0.05, keep_every=0))
    with TestClient(app) as client:
        created = client.post("/api/v1/builds", json={"name": "demo", "hcl": SAMPLE})
        assert created.status_code == 201
        run_id = created.json()["id"]
        deadline = time.monotonic() + 5
        body = created.json()
        while time.monotonic() < deadline and body["vnc_port"] is None:
            time.sleep(0.05)
            body = client.get(f"/api/v1/builds/{run_id}").json()
        port = body["vnc_port"]
        assert isinstance(port, int)
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen(1)
        received: list[bytes] = []

        def serve() -> None:
            conn, _addr = server.accept()
            with conn:
                conn.sendall(b"RFB 003.008\n")
                data = conn.recv(64)
                received.append(data)
                conn.sendall(b"ok:" + data)
            server.close()

        threading.Thread(target=serve, daemon=True).start()
        with client.websocket_connect(f"/api/v1/builds/{run_id}/vnc") as link:
            assert link.receive_bytes() == b"RFB 003.008\n"
            link.send_bytes(b"hello")
            assert link.receive_bytes() == b"ok:hello"
        assert received == [b"hello"]
        stopped = client.post(f"/api/v1/builds/{run_id}/cancel")
        assert stopped.status_code == 200
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and body["status"] == "running":
            time.sleep(0.05)
            body = client.get(f"/api/v1/builds/{run_id}").json()
        assert body["status"] == "cancelled"
        assert body["vnc_port"] is None
        try:
            with client.websocket_connect(f"/api/v1/builds/{run_id}/vnc"):
                pass
            raise AssertionError("websocket was accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008


def _app(tmp_path: Path, runner: BuildRunner):
    cfg = load_config(REPO_ROOT / "config" / "system.yaml")
    cfg.paths.work = str(tmp_path / "work")
    cfg.paths.history = str(tmp_path / "history.db")
    return create_app(cfg, manager=_Manager(), builds=runner)


async def _asleep() -> None:
    import asyncio

    await asyncio.sleep(0.05)
