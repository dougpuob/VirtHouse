"""VM spec, allocation, and API error paths. These tests do not start QEMU."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from virthouse.config.loader import load_config
from virthouse.config.models import SystemConfig
from virthouse.main import create_app
from virthouse.vm.errors import VmError
from virthouse.vm.models import RuntimeRecord, VmSpec
from virthouse.vm.network import assign_subnet, next_ordinal
from virthouse.vm.overlay import qemu_img_argv
from virthouse.vm.process import qemu_argv
from virthouse.vm.resources import ensure_capacity

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config() -> SystemConfig:
    cfg = load_config(REPO_ROOT / "config" / "system.yaml")
    cfg.resources.reserve_memory_mb = 0
    cfg.resources.reserve_cpus = 0
    cfg.resources.max_vm_memory_mb = 0
    cfg.resources.max_vm_cpus = 0
    return cfg


def test_assign_subnet_steps_the_third_octet() -> None:
    assert assign_subnet("192.168.100.0/24", 0) == (
        "192.168.100.0/24",
        "192.168.100.1",
        "192.168.100.2",
    )
    assert assign_subnet("192.168.100.0/24", 1) == (
        "192.168.101.0/24",
        "192.168.101.1",
        "192.168.101.2",
    )


def test_next_ordinal_skips_a_used_subnet() -> None:
    assert next_ordinal("192.168.100.0/24", {"192.168.100.0/24"}) == 1


def test_memory_insufficient_message() -> None:
    spec = VmSpec(name="a", base_image="base.qcow2", cpus=1, memory_mb=8192)
    with pytest.raises(VmError, match="memory insufficient \\(need 8192MB, available 4096MB\\)"):
        ensure_capacity(
            spec,
            _config(),
            host_memory_mb=4096,
            host_cpus=8,
            used_memory_mb=0,
            used_cpus=0,
        )


def test_qemu_commands_use_overlay_and_assigned_address(tmp_path: Path) -> None:
    record = RuntimeRecord(
        id="abc",
        name="demo",
        status="starting",
        base_image="base.qcow2",
        cpus=2,
        memory_mb=1024,
        overlay=str(tmp_path / "abc.qcow2"),
        qmp_socket=str(tmp_path / "abc.sock"),
        vnc_port=5900,
        subnet="192.168.100.0/24",
        gateway="192.168.100.1",
        guest_ip="192.168.100.2",
    )
    argv = qemu_argv("qemu-system-x86_64", record, ["-serial", "none"], kvm=False)
    assert argv[:3] == ["qemu-system-x86_64", "-name", "abc"]
    assert "-accel" in argv and argv[argv.index("-accel") + 1] == "tcg"
    assert f"file={record.overlay},if=virtio,format=qcow2" in argv
    assert "net=192.168.100.0/24,host=192.168.100.1,dhcpstart=192.168.100.2" in "".join(argv)
    assert argv[-2:] == ["-serial", "none"]
    assert qemu_img_argv(tmp_path / "base.qcow2", tmp_path / "abc.qcow2") == [
        "qemu-img",
        "create",
        "-f",
        "qcow2",
        "-b",
        str(tmp_path / "base.qcow2"),
        "-F",
        "qcow2",
        str(tmp_path / "abc.qcow2"),
    ]


def test_api_rejects_unknown_vm_and_bad_spec() -> None:
    app = create_app(_config())
    with TestClient(app) as client:
        missing = client.get("/api/v1/vms/nope")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "vm not found: nope"

        passthrough = client.post(
            "/api/v1/vms",
            json={
                "name": "demo",
                "base_image": "base.qcow2",
                "cpus": 1,
                "memory_mb": 512,
                "passthrough": ["0000:01:00.0"],
            },
        )
        assert passthrough.status_code == 400
        assert passthrough.json()["detail"] == "passthrough is not implemented"

        listed = client.get("/api/v1/vms")
        assert listed.status_code == 200
        assert listed.json() == []


def test_api_reports_insufficient_memory() -> None:
    cfg = _config()
    cfg.resources.reserve_memory_mb = 10**9
    app = create_app(cfg)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/vms",
            json={"name": "demo", "base_image": "base.qcow2", "cpus": 1, "memory_mb": 512},
        )
        assert response.status_code == 400
        assert response.json()["detail"].startswith("memory insufficient")
