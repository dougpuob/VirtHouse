function read() {
  try {
    const raw = localStorage.getItem("virthouse.passthrough");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    }
  } catch (_err) {
    return {};
  }
  const designs = {};
  try {
    const old = JSON.parse(localStorage.getItem("virthouse.allow") || "[]");
    if (Array.isArray(old)) {
      for (const id of old) designs[id] = { allowed: true, restore: true };
    }
  } catch (_err) {
    /* start empty */
  }
  return designs;
}

function write(all) {
  localStorage.setItem("virthouse.passthrough", JSON.stringify(all));
}

export function defaultPassName(device) {
  if (device.kind === "pci") return `HTX ${String(device.id).replace(/^0000:/, "")}`;
  return device.name;
}

function takeGuestSlot(used) {
  for (let slot = 6; slot < 32; slot += 1) {
    const text = `${slot.toString(16).padStart(2, "0")}.0`;
    if (!used.has(text)) return text;
  }
  return "1f.0";
}

export function ensurePassDesigns(devices) {
  const saved = read();
  const used = new Set();
  for (const device of devices) {
    const item = saved[device.id];
    if (item && item.allowed && typeof item.guestSlot === "string" && item.guestSlot) {
      used.add(item.guestSlot.toLowerCase());
    }
  }
  let changed = false;
  for (const device of devices) {
    const item = saved[device.id];
    if (!item || !item.allowed) continue;
    if (typeof item.name !== "string") {
      item.name = defaultPassName(device);
      changed = true;
    }
    if (device.kind === "pci" && typeof item.guestSlot !== "string") {
      item.guestSlot = takeGuestSlot(used);
      used.add(item.guestSlot);
      changed = true;
    }
    if (typeof item.restore !== "boolean") {
      item.restore = true;
      changed = true;
    }
  }
  if (changed || localStorage.getItem("virthouse.passthrough") == null) write(saved);
  return saved;
}

export function savePass(id, patch) {
  const all = read();
  all[id] = Object.assign({ allowed: false, restore: true }, all[id], patch);
  write(all);
  return all;
}

export function usbPlace(device) {
  if (device.bus != null && device.port != null) return { bus: device.bus, port: String(device.port) };
  const match = String(device.id).match(/^usb:(\d+)-([0-9.]+)$/);
  if (match) return { bus: match[1], port: match[2] };
  return { bus: "?", port: "?" };
}

export function slotOk(value) {
  return /^[0-9a-f]{1,2}\.[0-7]$/i.test(String(value || "").trim());
}

export function guestAttach(device, item, devices, saved) {
  if (!item || !item.allowed) return "";
  if (device.kind === "usb") {
    const place = usbPlace(device);
    return `usb-host,hostbus=${place.bus},hostport=${place.port}`;
  }
  const slot = String(item.guestSlot || "").trim();
  if (!slotOk(slot)) return "";
  const duplicate = devices.some((other) => {
    if (other.id === device.id || other.kind !== "pci") return false;
    const theirs = saved[other.id];
    return Boolean(theirs && theirs.allowed && String(theirs.guestSlot || "").trim().toLowerCase() === slot.toLowerCase());
  });
  if (duplicate) return "";
  return `vfio-pci,host=${device.id},addr=${slot.toLowerCase()}`;
}
