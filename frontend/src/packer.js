import { checksumReady } from "./iso.js";

export function newId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `draft-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function loadDrafts() {
  try {
    const saved = JSON.parse(localStorage.getItem("virthouse.packer") || "[]");
    if (!Array.isArray(saved)) return [];
    return saved.filter((item) => item && typeof item === "object").map((item) => ({
      ...blankDraft(),
      ...item,
      id: item.id || newId(),
      provisioners: Array.isArray(item.provisioners) ? item.provisioners : [],
    }));
  } catch (_err) {
    return [];
  }
}

export function saveDrafts(drafts) {
  localStorage.setItem("virthouse.packer", JSON.stringify(drafts));
}

export function blankDraft() {
  return {
    id: newId(),
    name: "",
    iso: "",
    iso_checksum: "",
    vm_name: "",
    disk_size: "40960M",
    machine_type: "q35",
    cpus: "2",
    memory: "2048",
    firmware: "bios",
    efi_code: "",
    efi_vars: "",
    boot_wait: "10s",
    boot_command: "",
    user_data: "",
    meta_data: "",
    communicator: "ssh",
    username: "",
    password: "",
    timeout: "5m",
    shutdown_command: "",
    shutdown_timeout: "5m",
    provisioners: [],
  };
}

export function workDirectory(config, name) {
  const root = config && config.paths && config.paths.work ? config.paths.work : "work";
  const leaf = String(name || "").trim().replace(/[\\/]/g, "") || "unnamed";
  return `${String(root).replace(/\/$/, "")}/${leaf}`;
}

export function isoPath(config, name) {
  if (!name) return "";
  const root = config && config.paths && config.paths.isos ? config.paths.isos : "";
  return root ? `${String(root).replace(/\/$/, "")}/${name}` : name;
}

function hclQuote(value) {
  return `"${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\r?\n/g, "\\n")}"`;
}

function hclBody(value) {
  if (!value) return '""';
  const marker = value.includes("EOF") ? "EOT" : "EOF";
  return `<<-${marker}\n${String(value).replace(/\s+$/, "")}\n${marker}`;
}

export function packerGaps(draft) {
  const gaps = [];
  if (!draft.name.trim()) gaps.push("name");
  if (!draft.iso) gaps.push("iso_url");
  if (!checksumReady(draft.iso_checksum)) gaps.push("iso_checksum");
  if (!draft.vm_name.trim()) gaps.push("vm_name");
  if (!/^\d+$/.test(draft.cpus)) gaps.push("cpus");
  if (!/^\d+$/.test(draft.memory)) gaps.push("memory");
  if (draft.firmware === "uefi" && !draft.efi_code.trim()) gaps.push("efi_firmware_code");
  if ((draft.user_data.trim() || draft.meta_data.trim()) && !draft.boot_command.trim()) gaps.push("boot_command");
  if (draft.communicator !== "none" && !draft.username.trim()) {
    gaps.push(draft.communicator === "winrm" ? "winrm_username" : "ssh_username");
  }
  if (draft.provisioners.some((item) => item.type === "shell" && !item.script.trim())) gaps.push("shell provisioner");
  if (draft.provisioners.some((item) => item.type === "file" && (!item.source.trim() || !item.destination.trim()))) gaps.push("file provisioner");
  return gaps;
}

export function packerHcl(config, draft) {
  const lines = [
    "packer {",
    "  required_plugins {",
    "    qemu = {",
    '      source  = "github.com/hashicorp/qemu"',
    '      version = ">= 1.1.0"',
    "    }",
    "  }",
    "}",
    "",
    'source "qemu" "image" {',
    `  iso_url           = ${hclQuote(isoPath(config, draft.iso))}`,
    `  iso_checksum      = ${hclQuote(draft.iso_checksum.trim())}`,
    `  vm_name           = ${hclQuote(draft.vm_name.trim())}`,
    '  format            = "qcow2"',
    `  disk_size         = ${hclQuote(draft.disk_size.trim() || "40960M")}`,
    '  accelerator       = "kvm"',
    `  machine_type      = ${hclQuote(draft.machine_type.trim() || "q35")}`,
    `  cpus              = ${/^\d+$/.test(draft.cpus) ? draft.cpus : 0}`,
    `  memory            = ${/^\d+$/.test(draft.memory) ? draft.memory : 0}`,
    '  disk_interface    = "virtio"',
    '  net_device        = "virtio-net"',
    `  output_directory  = ${hclQuote(workDirectory(config, draft.name))}`,
    "  headless          = true",
    `  boot_wait         = ${hclQuote(draft.boot_wait.trim() || "10s")}`,
  ];
  const command = String(draft.boot_command || "").split(/\r?\n/).filter((line) => line.length);
  if (command.length) {
    lines.push("  boot_command      = [");
    for (const line of command) lines.push(`    ${hclQuote(line)},`);
    lines.push("  ]");
  }
  if (draft.user_data.trim() || draft.meta_data.trim()) {
    lines.push("  http_content = {");
    if (draft.user_data.trim()) lines.push(`    "/user-data" = ${hclBody(draft.user_data)}`);
    if (draft.meta_data.trim()) lines.push(`    "/meta-data" = ${hclBody(draft.meta_data)}`);
    lines.push("  }");
  }
  if (draft.firmware === "uefi") {
    lines.push("  efi_boot          = true");
    lines.push(`  efi_firmware_code = ${hclQuote(draft.efi_code.trim())}`);
    if (draft.efi_vars.trim()) lines.push(`  efi_firmware_vars = ${hclQuote(draft.efi_vars.trim())}`);
    lines.push('  cdrom_interface   = "ide"');
  }
  lines.push(`  communicator      = ${hclQuote(draft.communicator)}`);
  if (draft.communicator === "ssh") {
    lines.push(`  ssh_username      = ${hclQuote(draft.username)}`);
    if (draft.password) lines.push(`  ssh_password      = ${hclQuote(draft.password)}`);
    lines.push(`  ssh_timeout       = ${hclQuote(draft.timeout.trim() || "5m")}`);
  } else if (draft.communicator === "winrm") {
    lines.push(`  winrm_username    = ${hclQuote(draft.username)}`);
    if (draft.password) lines.push(`  winrm_password    = ${hclQuote(draft.password)}`);
    lines.push(`  winrm_timeout     = ${hclQuote(draft.timeout.trim() || "5m")}`);
  }
  if (draft.shutdown_command.trim()) lines.push(`  shutdown_command  = ${hclQuote(draft.shutdown_command.trim())}`);
  lines.push(`  shutdown_timeout  = ${hclQuote(draft.shutdown_timeout.trim() || "5m")}`);
  lines.push("}", "", "build {", '  sources = ["source.qemu.image"]');
  for (const item of draft.provisioners) {
    if (item.type === "file") {
      if (!item.source.trim() || !item.destination.trim()) continue;
      lines.push('  provisioner "file" {', `    source      = ${hclQuote(item.source.trim())}`, `    destination = ${hclQuote(item.destination.trim())}`, "  }");
      continue;
    }
    const script = String(item.script || "").split(/\r?\n/).filter((line) => line.length);
    if (!script.length) continue;
    lines.push('  provisioner "shell" {', "    inline = [");
    for (const line of script) lines.push(`      ${hclQuote(line)},`);
    lines.push("    ]", "  }");
  }
  lines.push("}", "");
  return lines.join("\n");
}

export function finishedBuild(build) {
  const status = String(build.status || "").toLowerCase();
  return status === "done" || status === "ready" || status === "usable";
}
