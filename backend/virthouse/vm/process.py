"""QEMU command line and process control."""

from __future__ import annotations

import subprocess
from pathlib import Path

from virthouse.vm.models import RuntimeRecord


def qemu_argv(
    binary: str,
    record: RuntimeRecord,
    extra_args: list[str],
    *,
    kvm: bool,
) -> list[str]:
    if record.vnc_port is None or record.overlay is None or record.qmp_socket is None:
        raise ValueError("runtime record is missing overlay, qmp socket, or vnc port")
    display = record.vnc_port - 5900
    args = [
        binary,
        "-name",
        record.id,
        "-machine",
        "q35",
        "-accel",
        "kvm" if kvm else "tcg",
        "-m",
        str(record.memory_mb),
        "-smp",
        str(record.cpus),
        "-drive",
        f"file={record.overlay},if=virtio,format=qcow2",
        "-netdev",
        (
            "user,id=net0,"
            f"net={record.subnet},host={record.gateway},dhcpstart={record.guest_ip}"
        ),
        "-device",
        "virtio-net-pci,netdev=net0",
        "-qmp",
        f"unix:{record.qmp_socket},server,nowait",
    ]
    if record.qga_socket:
        args.extend(
            [
                "-chardev",
                f"socket,id=qga0,path={record.qga_socket},server=on,wait=off",
                "-device",
                "virtio-serial",
                "-device",
                "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
            ]
        )
    args.extend(
        [
            "-display",
            "none",
            "-vnc",
            f"127.0.0.1:{display}",
        ]
    )
    args.extend(extra_args)
    return args


def spawn(args: list[str], log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("ab")
    try:
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    finally:
        log_file.close()
