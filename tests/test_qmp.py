"""QMP snapshot shaping and the host resource page."""

from fastapi.testclient import TestClient

from virthouse.config.loader import load_config
from virthouse.main import create_app
from virthouse.vm.qmp import assemble_snapshot, parse_console_line

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_assemble_snapshot_keeps_vm_resources() -> None:
    view = assemble_snapshot(
        {"status": "running", "running": True},
        [{"cpu-index": 0, "thread-id": 10, "props": {"core-id": 0}}],
        {"base-memory": 2 * 1024 * 1024 * 1024, "plugged-memory": 0},
        [
            {
                "device": "virtio0",
                "inserted": {"drv": "qcow2", "image": {"virtual-size": 512 * 1024 * 1024}},
            },
            {"device": "ide2-cd0", "inserted": None},
        ],
        [{"device": "virtio0", "stats": {"rd_bytes": 3 * 1024 * 1024, "wr_bytes": 1024 * 1024}}],
        {"enabled": True},
        {"qemu": {"major": 11, "minor": 0, "micro": 90}},
    )
    assert view.status == "running"
    assert view.kvm is True
    assert view.qemu_version == "11.0.90"
    assert view.cpu_count == 1
    assert view.memory_base_mb == 2048
    assert len(view.blocks) == 1
    assert view.blocks[0].device == "virtio0"
    assert view.blocks[0].virtual_mb == 512
    assert view.blocks[0].read_mb == 3
    assert view.blocks[0].written_mb == 1
    assert view.guest_agent is False


def test_console_line_routes_monitor_and_qmp() -> None:
    assert parse_console_line("info status") == (
        "human-monitor-command",
        {"command-line": "info status"},
    )
    assert parse_console_line('{"execute": "query-kvm"}') == ("query-kvm", None)
    assert parse_console_line('{"execute": "query-block", "arguments": {}}') == (
        "query-block",
        {},
    )


def test_qmp_console_rejects_unknown_vm() -> None:
    app = create_app(load_config(REPO_ROOT / "config" / "system.yaml"))
    with TestClient(app) as client:
        response = client.post("/api/v1/vms/nope/qmp/execute", json={"command": "info status"})
    assert response.status_code == 404
    assert response.json()["detail"] == "vm not found: nope"


def test_resources_endpoint_reports_this_host() -> None:
    app = create_app(load_config(REPO_ROOT / "config" / "system.yaml"))
    with TestClient(app) as client:
        response = client.get("/api/v1/resources")
    assert response.status_code == 200
    body = response.json()
    assert body["hostname"]
    assert body["cpu_count"] >= 1
    assert body["memory_total_mb"] > body["memory_available_mb"] >= 0
    assert any(item["name"] == "virthouse" for item in body["processes"])
