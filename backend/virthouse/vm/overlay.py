"""qcow2 overlay files. Guest writes go here; the base image is unchanged."""

from __future__ import annotations

import subprocess
from pathlib import Path

from virthouse.vm.errors import VmError


def qemu_img_argv(base: Path, overlay: Path) -> list[str]:
    return [
        "qemu-img",
        "create",
        "-f",
        "qcow2",
        "-b",
        str(base),
        "-F",
        "qcow2",
        str(overlay),
    ]


def create_overlay(base: Path, overlay: Path) -> None:
    overlay.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        qemu_img_argv(base, overlay),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise VmError(f"overlay create failed: {detail}")


def delete_overlay(overlay: Path) -> None:
    if overlay.is_file():
        overlay.unlink()
