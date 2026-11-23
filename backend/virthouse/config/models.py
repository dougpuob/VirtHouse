"""Pydantic models for VirtHouse system configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class PathsConfig(BaseModel):
    isos: str = "~/virthouse/isos"
    bases: str = "~/virthouse/bases"
    work: str = "~/virthouse/work"
    overlays: str = "~/virthouse/overlays"
    qmp: str = "~/virthouse/qmp"

    @field_validator("*", mode="before")
    @classmethod
    def expand_user(cls, value: object) -> object:
        """Expand ``~`` so runtime paths sit under the current user's home."""
        if isinstance(value, str):
            return str(Path(value).expanduser())
        return value


class QemuConfig(BaseModel):
    binary: str = "qemu-system-x86_64"
    extra_args: list[str] = Field(default_factory=list)


class ResourcesConfig(BaseModel):
    reserve_memory_mb: int = 2048
    reserve_cpus: int = 2
    max_vm_memory_mb: int = 0
    max_vm_cpus: int = 0


class NetworkConfig(BaseModel):
    subnet_base: str = "192.168.100.0/24"
    guest_gateway: str = "192.168.100.1"
    guest_ip: str = "192.168.100.2"


class TimeoutsConfig(BaseModel):
    process_start_sec: int = 30
    basic_ready_sec: int = 60
    system_ready_linux_sec: int = 180
    system_ready_windows_sec: int = 300
    overall_sec: int = 600


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class SystemConfig(BaseModel):
    """VirtHouse process settings (paths, qemu binary, host policy).

    Base images are not listed here. Image storage and metadata live under
    design.md section 3 (Image management).
    """

    paths: PathsConfig = Field(default_factory=PathsConfig)
    qemu: QemuConfig = Field(default_factory=QemuConfig)
    resources: ResourcesConfig = Field(default_factory=ResourcesConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
