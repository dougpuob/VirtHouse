"""VM spec and the runtime record created at start."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VmSpec(BaseModel):
    """What one VM should be. This is not system config."""

    name: str
    base_image: str
    cpus: int = Field(ge=1)
    memory_mb: int = Field(ge=1)
    passthrough: list[str] = Field(default_factory=list)
    ready_check: str = "basic"
    ready_timeout_sec: int | None = None
    extra_qemu_args: list[str] = Field(default_factory=list)


class RuntimeRecord(BaseModel):
    """What one VM was actually given. Lives in backend memory."""

    id: str
    name: str
    status: str
    error: str | None = None
    base_image: str
    cpus: int
    memory_mb: int
    pid: int | None = None
    overlay: str | None = None
    qmp_socket: str | None = None
    qga_socket: str | None = None
    vnc_port: int | None = None
    subnet: str | None = None
    gateway: str | None = None
    guest_ip: str | None = None


class VmStatusView(BaseModel):
    id: str
    status: str
    ready: bool
    error: str | None = None


class QmpCpu(BaseModel):
    index: int
    thread_id: int
    core_id: int | None = None


class QmpBlock(BaseModel):
    device: str
    driver: str | None = None
    virtual_mb: int | None = None
    read_mb: int = 0
    written_mb: int = 0


class QmpView(BaseModel):
    """What QEMU reports about one VM. This is not the host."""

    status: str
    running: bool
    kvm: bool
    qemu_version: str
    cpu_count: int
    cpus: list[QmpCpu]
    memory_base_mb: int
    memory_plugged_mb: int
    blocks: list[QmpBlock]
    guest_agent: bool = False


class QmpCommand(BaseModel):
    """One line typed into the QMP console."""

    command: str


class QmpCommandResult(BaseModel):
    """Text to append to the QMP console."""

    output: str
