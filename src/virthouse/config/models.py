"""Pydantic models for VirtHouse system configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    isos: str = "/var/lib/qemu-manager/isos"
    bases: str = "/var/lib/qemu-manager/bases"
    work: str = "/var/lib/qemu-manager/work"
    overlays: str = "/var/lib/qemu-manager/overlays"
    qmp: str = "/var/lib/qemu-manager/qmp"


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


class BaseImageEntry(BaseModel):
    file: str
    os_type: str = "linux"
    description: str = ""


class SystemConfig(BaseModel):
    """Top-level system configuration (DESIGN.md §10.1)."""

    paths: PathsConfig = Field(default_factory=PathsConfig)
    qemu: QemuConfig = Field(default_factory=QemuConfig)
    resources: ResourcesConfig = Field(default_factory=ResourcesConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    base_images: dict[str, BaseImageEntry] = Field(default_factory=dict)
