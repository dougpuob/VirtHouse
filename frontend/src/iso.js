export function isoRecords() {
  try {
    const saved = JSON.parse(localStorage.getItem("virthouse.iso") || "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch (_err) {
    return {};
  }
}

export function commitIso(name, patch) {
  const all = isoRecords();
  const next = Object.assign({}, all[name], patch);
  if (typeof next.checksum === "string") next.checksum = next.checksum.trim();
  if (!next.checksum) delete next.checksum;
  if (typeof next.title === "string" && !next.title.trim()) delete next.title;
  if (Object.keys(next).length) all[name] = next;
  else delete all[name];
  localStorage.setItem("virthouse.iso", JSON.stringify(all));
  return all;
}

export function parseIsoName(filename) {
  const stem = String(filename).replace(/\.iso$/i, "");
  const ubuntu = stem.match(/^ubuntu-(\d+\.\d+(?:\.\d+)?)-(desktop|server|live)(?:-([a-z0-9_]+))?$/i);
  if (ubuntu) {
    const edition = ubuntu[2].charAt(0).toUpperCase() + ubuntu[2].slice(1).toLowerCase();
    return {
      title: `Ubuntu ${ubuntu[1]} ${edition}`,
      os: "Ubuntu",
      edition,
      arch: (ubuntu[3] || "amd64").toLowerCase(),
      firmware: "uefi",
      boots: ["uefi", "bios"],
    };
  }
  const windows = /windows|win(?:11|10|server)/i.test(stem);
  const arch = (stem.match(/-(amd64|arm64|x86_64|i386)$/i) || [])[1] || "";
  return {
    title: stem,
    os: windows ? "Windows" : "Other",
    edition: "",
    arch: arch.toLowerCase().replace("x86_64", "amd64"),
    firmware: windows ? "uefi" : "bios",
    boots: windows ? ["uefi"] : ["bios"],
  };
}

export function mediaOf(iso, saved = isoRecords()) {
  const record = saved[iso.name] || {};
  const parsed = parseIsoName(iso.name);
  const osList = ["Ubuntu", "Debian", "Fedora", "Windows", "Other"];
  const os = record.os || iso.os || parsed.os || "Other";
  const firmware = record.firmware || iso.firmware || parsed.firmware || "bios";
  const boots = Array.isArray(iso.boots) && iso.boots.length ? iso.boots : parsed.boots;
  return {
    title: (record.title || iso.title || parsed.title).trim(),
    os: osList.includes(os) ? os : "Other",
    edition: iso.edition || parsed.edition || "",
    arch: iso.arch || parsed.arch || "",
    firmware: firmware === "uefi" ? "uefi" : "bios",
    boots: boots.map((item) => (item === "uefi" ? "uefi" : "bios")),
    checksum: record.checksum || iso.checksum || "",
  };
}

export function checksumReady(value) {
  const text = String(value || "").trim();
  if (/^file:\S/.test(text)) return true;
  return /^(md5|sha1|sha256|sha512):[0-9a-fA-F]+$/.test(text);
}

export function formatBytes(bytes) {
  if (!bytes) return "—";
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
