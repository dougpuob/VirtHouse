# VirtHouse Design

**Version**: 6
**Date**: 2026-11-23
**Status**: Draft for prototype implementation
**Supersedes**: [DESIGN_v5.md](doc/designdoc/DESIGN_v5.md)

## Changes from v5

1. The left menu is a collapse: Dashboard, Machines, Builder, Resource, and Settings. Dashboard stays at the top and Settings stays at the bottom. Those two have no list. Machines, Builder, and Resource are panels. Clicking a panel header expands or collapses its list, and more than one list can be open. Builder itself is a dashboard. Under it, Creating and Dump are separate pages. A build starts in Creating and moves to Dump when it finishes. Resource opens into ISO image and Pass-through device. ISO image chooses a file. Pass-through device is the table that turns an allowed host device into a resource a guest can take.
2. Builds and usable images are recorded in `config/images.yaml`. `config/system.yaml` still does not list images and has nothing to do with a build.

From this version on, source code, configuration files, and design documents are written in English.

## Changes from v4

1. Each pane shows one window. The dropdown in a pane is that pane's window list.
2. The Information window is the host-side record of one VM: Status, Configuration, Runtime, and Network. Runtime is the overlay, the QMP socket, the guest agent socket, and the VNC port.
3. SSH connection list is a tabbed window. Its first tab tries SSH to the guest. When that cannot connect, the tab shows why. Screen view remains the way to see and operate a guest that has no SSH server. Screen control records that display, takes a screenshot, and sends desktop actions through it.

## Changes from v3

1. A VM's CPU count and memory size are set with QEMU `-smp` and `-m`. VirtHouse does not use cgroup.

## Changes from v2

1. `config/system.yaml` does not contain the API listen address or port.
2. `config/system.yaml` does not contain a guest IP or a guest gateway.
3. Extra QEMU arguments belong on the VM spec only. The system config only names the QEMU binary.

## Changes from v1

1. Storage paths default to the current user's home: `~/virthouse/...`.
2. `config/system.yaml` is the settings file for the VirtHouse process. One file per host. It is not a VM spec and it does not list base images.
3. A VM's CPU count, memory size, and assigned guest address belong to the VM spec and the VM's runtime record.
4. The repository is split into `backend/` and `frontend/`. The backend process starts and watches QEMU itself. There is no separate VM-manager daemon.
5. Base images are managed by image management. The system config only stores the directory path.

## 1. Overview

### 1.1 Goals

On one Ubuntu x86 host, VirtHouse must be able to:

- Start many clean, writable, non-persistent QEMU VMs from a prepared base image.
- Manage those VMs from a WebUI, including noVNC display and input.
- Expose a REST API so an external CI system can request a VM, wait until it is ready, run tests, and release it.
- Support PCIe and USB passthrough, and manage the allowed devices from the WebUI.
- Read live VM state through QMP.
- Build and manage base images, including ISOs.

### 1.2 Out of scope for the prototype

- Multi-user authorization. Single operator.
- High availability and clustering.
- Live migration.
- A second long-running process that owns QEMU. The backend process owns that work.

### 1.3 Stack

- **Backend**: Python 3 + FastAPI, one process
- **Frontend**: a small SPA (Vue 3 or similar) + noVNC
- **Virtualization**: `qemu-system-x86_64`, including a custom-built binary
- **Disk**: qcow2 base + overlay
- **Limits**: QEMU `-smp` and `-m`
- **Status**: QMP (QEMU Machine Protocol)
- **Display**: QEMU VNC + noVNC (WebSocket)

## 2. Repository layout

```
DESIGN_v6.md                      Current design
doc/designdoc/                    Older design documents (DESIGN_v1.md, DESIGN_v2.md, DESIGN_v3.md, DESIGN_v4.md, DESIGN_v5.md, …)
backend/virthouse/                FastAPI process: API, system config, VM lifecycle, QMP
frontend/                         WebUI
config/system.yaml                Process settings for this host
config/images.yaml                Build status and usable-image status
```

`backend/virthouse` is one Python package. VM start, stop, overlay files, and QMP live in that package. The frontend is a separate program and talks to the backend over HTTP and WebSocket.

The backend may later be launched by systemd. That does not add a second VirtHouse daemon. QEMU child processes are started with `subprocess` from the backend and monitored from the same process.

```
┌────────────┐     ┌────────────┐
│   WebUI    │     │  CI system │
│  (browser) │     │            │
└──────┬─────┘     └──────┬─────┘
       │ REST / WS        │ REST
       ▼                  ▼
┌───────────────────────────────────┐
│     Backend process (FastAPI)     │
│  - VM lifecycle                   │
│  - Resource check and allocation  │
│  - QMP client                     │
│  - Device passthrough            │
│  - Image / ISO management         │
│  - System config and templates    │
└──────────────┬────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
┌────────────┐  ┌────────────┐
│ QEMU procs │  │ Host       │
│ + QMP      │  │ (vfio)     │
│ + VNC      │  │            │
└────────────┘  └────────────┘
```

## 3. Storage and image management

### 3.1 Directories

Paths are set in `config/system.yaml` and `~` is expanded to the current user's home. Defaults:

- `~/virthouse/isos/` — ISO files
- `~/virthouse/bases/` — published base images (qcow2)
- `~/virthouse/work/` — images being built, install disks
- `~/virthouse/overlays/` — overlay files for VMs
- `~/virthouse/qmp/` — QMP socket files

Which images exist is not written in `system.yaml`. `config/images.yaml` records two lists:

- `builds` — each Packer build and its status. Packer writes the new disk into the work directory. That temporary QEMU is not a VirtHouse machine.
- `images` — each disk a machine may start from, and whether that disk is usable. `file` is the name inside the bases directory.

The files on disk stay in the directories above. The catalog records status. It does not copy the disks.

### 3.2 Image lifecycle

1. Upload or place an ISO in the ISO directory.
2. From the WebUI, create an install VM: choose an ISO and a spec, then boot it and install through noVNC.
3. After install (tools, virtio drivers, and so on) and shutdown, promote that disk to a base image.
4. Later test VMs use that base image. Each start creates a new overlay.

### 3.3 Picker

The WebUI has one file and image picker. It can browse, upload, rename, and delete ISOs and base images, and it shows the metadata from section 3.1.

## 4. VM lifecycle and disks

Three different records are involved. They are not stored in the same file.

| Record | What it answers | Where it lives |
| --- | --- | --- |
| System config | How this host runs VirtHouse | `config/system.yaml` |
| VM spec / template | What this VM should be | Request body or a saved template |
| Runtime record | What this VM was actually given | Backend memory while the VM exists |

### 4.1 Start sequence

1. Accept a start request (WebUI or API) carrying a VM spec.
2. Check host resources (CPU, memory, and whether the requested passthrough devices are free).
3. If something is short, return a specific error, for example `memory insufficient (need 8192MB, available 4096MB)`.
4. Create an overlay qcow2 whose backing file is the chosen base image.
5. Prepare passthrough devices (unbind, then bind vfio, and so on).
6. Start the QEMU process from the backend, with `-smp`, `-m`, a QMP socket, and VNC.
7. Poll until the VM is ready or the attempt times out.

### 4.2 Overlay and reset

- Guest writes go to the overlay.
- Reset means: stop the VM, delete the overlay, create a new overlay, and start again. Deleting the overlay and recreating it on the next start is also acceptable.
- After shutdown, keep the overlay until an explicit reset or until the VM is deleted.

### 4.3 Runtime record

Created when a VM starts. Not part of `system.yaml`. It holds the VM id, QEMU pid, overlay path, QMP socket path, VNC port, assigned subnet and guest address, and status.

## 5. Resources

Before start, the backend checks free host CPU and memory and keeps the reserve from the system config. The VM's CPU count and memory size are passed to QEMU with `-smp` and `-m`. The backend watches the process and can report or clean up a crash.

The VM spec says how much this VM needs. The system config says how much of the host must stay free, and the maximum one VM is allowed to request. A zero maximum means no ceiling.

## 6. Passthrough devices

### 6.1 Types

- PCIe through vfio-pci
- USB through usb-host

### 6.2 Management

- The backend scans the host (`lspci`, `lsusb`, sysfs).
- The pass-through page is one table. Each row is a device on this host.
- Allow is the gate on that row. Until the row is allowed, the device stays on the host and no guest can take it. Allowing the row makes that device a resource a guest can be given.
- The allowed row is where that passthrough is designed:
  - the name a guest uses to request the device
  - PCI: the guest receives `vfio-pci` at the host address, on a PCI slot set in the row. An IOMMU group moves together. A group that contains only this device can be allowed by itself.
  - USB: the guest receives `usb-host` bound to the host bus and port
  - whether the host driver is bound again when the guest stops
- The row shows which guest holds the device. One guest holds an allowed device at a time. A device that is not allowed is held by the host.
- A start request may name only allowed devices.
- Devices are assigned before start. Hot-plug of PCIe after start is not the main path.

### 6.3 Requirements

- The host must have IOMMU enabled.
- Before start: unbind the current driver, then bind vfio-pci.
- After stop: optionally bind the original driver again.
- Bind, unbind, and rollback failures must be handled and logged.

## 7. Network

Each VM gets its own subnet, for example `192.168.100.0/24`, and reaches the outside through NAT. The guest address must be predictable (static DHCP or an address set at start).

`config/system.yaml` stores the first subnet (`subnet_base`). It does not store a guest address or a gateway. The address and gateway assigned at start are written into that VM's runtime record.

## 8. QMP

- Each VM opens a QMP unix socket at start.
- The backend is the QMP client:
  - queries `query-status`, CPU, block devices, PCI, USB
  - listens for events such as `SHUTDOWN`, `GUEST_PANICKED`, and device changes
- Basic readiness depends on this.
- The API and WebUI expose the summarized information.
- A restricted QMP execute endpoint may exist, limited to an allow-list.

## 9. Readiness and timeouts

### 9.1 Conditions

1. **Basic ready**: QEMU process is alive, QMP `query-status` is `running`, and VNC accepts a connection.
2. **System ready**: SSH port, guest agent, or a custom check. Linux and Windows may differ.
3. **Test ready**: defined by the VM spec.

### 9.2 Polling

- A task inside the backend process polls.
- States: `pending` → `starting` → `booting` → `ready` / `failed` / `timeout`.
- Poll more often at the beginning and less often later.

### 9.3 Timeouts

Defaults live in the system config. Suggested values:

- Process start: 30s
- Basic ready: 60s
- System ready: Linux 180s, Windows 300s
- Overall limit: 600s

On timeout, the default is to stop the VM, delete the overlay, release devices, and record the error. An operator start may instead keep the failed VM for inspection.

## 10. Config and templates

### 10.1 System config

File: `config/system.yaml`. Override with `VIRTHOUSE_CONFIG=/path/to/file.yaml`.

This file configures the VirtHouse process on this host:

- Directory paths (ISO, base, work, overlay, QMP)
- Default QEMU binary for this host
- Host reserve (CPU and memory that must stay free) and optional per-VM ceilings
- First subnet (`subnet_base`)
- Default timeouts

It does not contain:

- The list of base images, build status, or usable-image status. Those are recorded in `config/images.yaml`
- One VM's name, CPU count, memory size, passthrough devices, or extra QEMU arguments
- One VM's guest IP or gateway
- The address and port the API process listens on. Those are startup parameters (`VIRTHOUSE_HOST`, `VIRTHOUSE_PORT`)

### 10.2 VM spec / template

Saved and loaded from the WebUI as a form or as YAML. A start request sends the same shape:

- Name
- Base image
- CPU count
- Memory
- Passthrough devices
- Ready-check type and timeout
- Extra QEMU arguments

A spec may override the network rule. If it does not, the backend assigns a subnet from the system rule.

## 11. REST API (draft)

### VMs

- `POST /api/v1/vms` — start a VM. Body is a VM spec.
- `GET /api/v1/vms` — list VMs
- `GET /api/v1/vms/{id}` — detail, including the runtime record
- `GET /api/v1/vms/{id}/status` — status, readiness, and error
- `POST /api/v1/vms/{id}/reset` — reset
- `DELETE /api/v1/vms/{id}` — stop and clean up
- `GET /api/v1/vms/{id}/qmp/...` — QMP queries

### Resources and devices

- `GET /api/v1/resources` — free host resources
- `GET /api/v1/devices` — devices and whether each is in use
- `PUT /api/v1/devices/{id}` — allow or disallow, and set the display name

### Images

- `GET /api/v1/images` — the catalog in `config/images.yaml`: build status and usable-image status
- `GET /api/v1/images/bases`
- `GET /api/v1/images/isos`
- `POST /api/v1/images/upload`
- `POST /api/v1/images/promote` — promote a work image to a base image

### Config

- `GET/PUT /api/v1/config` — the system config
- `GET/POST/PUT/DELETE /api/v1/templates` — VM templates

Every error response includes a specific message.

## 12. WebUI pages

The left menu is a collapse. Dashboard is the top header and Settings is the bottom header. Neither has a list. Machines, Builder, and Resource are panels: the header has an arrow, and clicking it expands or collapses the list under it. More than one panel can be open. Expanding Machines lists this computer and the VMs under it. Expanding Builder shows the builder dashboard and lists Creating and Dump. Those two are separate pages. A build starts in Creating, as a plan and then a running build. When it finishes, it moves to Dump. Expanding Resource lists ISO image and Pass-through device. ISO image chooses a file. Pass-through device is the table where a host device is allowed and designed into something a guest can take.

1. **Dashboard** — running VMs, host resources, shortcuts.
2. **VM management** — start a VM (base, spec, devices, template); noVNC, reset, and stop; status and QMP.
3. **Device management** — the pass-through table: allow a host device, name it, set what the guest receives, and see which guest holds it.
4. **Image management** — browse ISO, base, and work directories; picker; create an install VM; promote to base.
5. **Config / templates** — edit the system config; edit templates as a form or as YAML.

noVNC is a window, not a separate application page.

### 12.1 Windows and the window list

The area to the right of the resource tree is a grid of panes. Each pane displays one **window**. The dropdown at the top of a pane is that pane's **window list**. Choosing an entry replaces the window in that pane. Panes can be resized with the splitters. The list follows the resource selected in the tree: a host and a VM do not offer the same windows.

Host windows: Dashboard, Host, Config, Devices, Images.

VM windows:

| Window | What it shows |
| --- | --- |
| Screen view | The guest display through noVNC. |
| Screen control | Recording, screenshot, and desktop actions on the Screen view display. See section 12.4. |
| Information | The host-side record of this VM. |
| Network | Subnet, gateway, and guest address. |
| QMP status | What QEMU reports without a guest agent, plus whether the agent is connected. |
| QMP console | A QEMU monitor. A JSON object is sent as QMP. |
| SSH connection list | Tabbed SSH attempts. See section 12.3. |

### 12.2 Information

Information is one window. It has four parts:

1. **Status** — VM status, error, and the QEMU pid.
2. **Configuration** — name, id, base image, CPU count, and memory. This is the spec the host applied.
3. **Runtime** — objects the host created for this VM: overlay file, QMP socket, guest agent socket, and VNC port.
4. **Network** — subnet, gateway, and guest address assigned on the host.

### 12.3 SSH connection list

This window supports tabs. It opens with one default tab, titled SSH, aimed at the guest address on port 22. The operator can open more tabs.

The default tab does not pretend a session exists. When SSH cannot be opened, the tab stays up and shows the reason together with the facts already on the runtime record:

- The VM is not running, so there is no guest.
- The guest has no address yet.
- The address exists, but this host cannot open a TCP connection to it. User-mode networking does not publish a host port.
- The guest has no SSH server. A newly created machine is in this state until an SSH server is installed and running inside the guest.

Screen view is the control path that needs nothing installed in the guest. QEMU is already drawing that display. A serial console can be a later window: QEMU can provide the port without an extra package, and a login appears only when the image already runs a getty on that port. Neither Screen view nor a serial port requires an SSH server. SSH connection list is for a guest that already has one.

### 12.4 Screen view and Screen control

Screen view is the guest display. Screen control does not open a second display. It operates on the display connected in Screen view:

1. **Recording** saves a WebM of that display.
2. **Screenshot** saves a PNG of that display.
3. **Desktop** actions are sent through that same VNC session: Ctrl+Alt+Del, Super, Alt+Tab, Show desktop, Escape, and typing text into whatever has focus in the guest.

Screen control can act only while Screen view is connected.

## 13. Implementation notes

- Manage QEMU with `subprocess` and asynchronous monitoring inside the backend process.
- Use an existing Python QMP library, or a small client.
- Passthrough needs root or equivalent capability. Run the backend with only the privileges it needs.
- Log start, stop, device bind, and file deletion.
- Prototype order: start, stop, overlay, noVNC, and the basic VM API. Then passthrough, richer QMP, and image build.
- A Windows base image should include virtio-win. Consider sysprep.
- The QEMU binary path is configurable so a custom build can be used.

## 14. Later

- Deeper guest-agent integration
- Finer network settings (bridge, fixed MAC)
- Snapshot versions
- Webhooks to CI
- Split QEMU management into its own process only if an API restart must leave VMs running, or if QEMU management must run as root while the API runs as a normal user

---

The current design is `DESIGN_v5.md` at the repository root. When it is replaced, move that file into `doc/designdoc/` and leave the new version at the root as `DESIGN_v6.md`. Do not edit files already in `doc/designdoc/`.
