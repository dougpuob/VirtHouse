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
    vnc_port: int | None = None
    subnet: str | None = None
    gateway: str | None = None
    guest_ip: str | None = None


class VmStatusView(BaseModel):
    id: str
    status: str
    ready: bool
    error: str | None = None
