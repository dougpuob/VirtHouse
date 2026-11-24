const DESKTOP_KEY = {
  Escape: ["Escape", 0xff1b],
  Super: ["MetaLeft", 0xffeb],
  Alt: ["AltLeft", 0xffe9],
  Tab: ["Tab", 0xff09],
  Shift: ["ShiftLeft", 0xffe1],
  KeyD: ["KeyD", 0x64],
};

let recording = null;

export function screenSession(frame) {
  try {
    const api = frame && frame.contentWindow && frame.contentWindow.virthouseScreen;
    if (!api || !api.rfb || !api.connected) {
      return null;
    }
    const canvas = api.canvas();
    if (!canvas) {
      return null;
    }
    return { rfb: api.rfb, canvas };
  } catch (_err) {
    return null;
  }
}

export function recordingFor(vmId) {
  return recording && recording.vmId === vmId ? recording : null;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function fileStamp() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function fileSlug(name) {
  const slug = String(name || "vm").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return slug || "vm";
}

export function stopScreenRecording(save) {
  const job = recording;
  if (!job) {
    return;
  }
  job.save = save;
  recording = null;
  if (job.recorder.state !== "inactive") {
    job.recorder.stop();
  }
}

export function startScreenRecording(vm, session, onDone) {
  const source = (session.rfb._display && session.rfb._display._backbuffer) || session.canvas;
  if (!source || !source.width || typeof MediaRecorder !== "function") {
    return "This browser cannot record the display.";
  }
  const mime = ["video/webm;codecs=vp8", "video/webm"].find((type) => MediaRecorder.isTypeSupported(type));
  if (!mime) {
    return "This browser cannot record the display.";
  }
  const canvas = document.createElement("canvas");
  canvas.width = source.width;
  canvas.height = source.height;
  canvas.style.cssText = "position:fixed;width:1px;height:1px;opacity:0;pointer-events:none";
  document.body.append(canvas);
  const ctx = canvas.getContext("2d");
  let stream;
  try {
    stream = canvas.captureStream(0);
  } catch (_err) {
    canvas.remove();
    return "The display could not be recorded.";
  }
  const [track] = stream.getVideoTracks();
  if (!track || typeof track.requestFrame !== "function") {
    for (const item of stream.getTracks()) item.stop();
    canvas.remove();
    return "This browser cannot record the display.";
  }
  const grab = () => {
    if (!source.width) return;
    if (canvas.width !== source.width || canvas.height !== source.height) {
      canvas.width = source.width;
      canvas.height = source.height;
    }
    ctx.drawImage(source, 0, 0);
    track.requestFrame();
  };
  const recorder = new MediaRecorder(stream, { mimeType: mime });
  const chunks = [];
  const frames = setInterval(grab, 100);
  const job = { recorder, started: Date.now(), vmId: vm.id, save: true };
  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size) chunks.push(event.data);
  };
  recorder.onstop = () => {
    clearInterval(frames);
    for (const item of stream.getTracks()) item.stop();
    canvas.remove();
    const message = !job.save ? "" : chunks.length ? "Saved the recording." : "Recording was empty.";
    if (job.save && chunks.length) {
      downloadBlob(new Blob(chunks, { type: mime }), `screen-${fileSlug(vm.name)}-${fileStamp()}.webm`);
    }
    if (onDone) onDone(message);
  };
  grab();
  recorder.start(250);
  recording = job;
  return "";
}

export function saveScreenshot(vm, rfb, onDone) {
  rfb.toBlob((blob) => {
    if (!blob) {
      onDone("Screenshot failed.");
      return;
    }
    downloadBlob(blob, `screen-${fileSlug(vm.name)}-${fileStamp()}.png`);
    onDone("Saved the screenshot.");
  }, "image/png");
}

export function sendTap(rfb, name) {
  const [code, keysym] = DESKTOP_KEY[name];
  rfb.sendKey(keysym, code, true);
  rfb.sendKey(keysym, code, false);
}

export function sendChord(rfb, names) {
  const keys = names.map((name) => DESKTOP_KEY[name]);
  for (const [code, keysym] of keys) rfb.sendKey(keysym, code, true);
  for (const [code, keysym] of [...keys].reverse()) rfb.sendKey(keysym, code, false);
}

function keyPlan(char) {
  const letters = "abcdefghijklmnopqrstuvwxyz";
  const letter = letters.indexOf(char.toLowerCase());
  if (letter >= 0) {
    return { code: `Key${letters[letter].toUpperCase()}`, keysym: char.charCodeAt(0), shift: char !== letters[letter] };
  }
  if (char >= "0" && char <= "9") {
    return { code: `Digit${char}`, keysym: char.charCodeAt(0), shift: false };
  }
  const plain = {
    " ": ["Space", 0x20], "\n": ["Enter", 0xff0d], "-": ["Minus", 0x2d], "=": ["Equal", 0x3d],
    "[": ["BracketLeft", 0x5b], "]": ["BracketRight", 0x5d], "\\": ["Backslash", 0x5c],
    ";": ["Semicolon", 0x3b], "'": ["Quote", 0x27], ",": ["Comma", 0x2c], ".": ["Period", 0x2e],
    "/": ["Slash", 0x2f], "`": ["Backquote", 0x60],
  };
  const shifted = {
    "!": ["Digit1", 0x21], "@": ["Digit2", 0x40], "#": ["Digit3", 0x23], $: ["Digit4", 0x24],
    "%": ["Digit5", 0x25], "^": ["Digit6", 0x5e], "&": ["Digit7", 0x26], "*": ["Digit8", 0x2a],
    "(": ["Digit9", 0x28], ")": ["Digit0", 0x29], _: ["Minus", 0x5f], "+": ["Equal", 0x2b],
    "{": ["BracketLeft", 0x7b], "}": ["BracketRight", 0x7d], "|": ["Backslash", 0x7c],
    ":": ["Semicolon", 0x3a], '"': ["Quote", 0x22], "<": ["Comma", 0x3c], ">": ["Period", 0x3e],
    "?": ["Slash", 0x3f], "~": ["Backquote", 0x7e],
  };
  const found = plain[char] || shifted[char];
  if (!found) return null;
  return { code: found[0], keysym: found[1], shift: Boolean(shifted[char]) };
}

export function typeIntoDesktop(rfb, text) {
  let skipped = 0;
  for (const char of text) {
    const plan = keyPlan(char);
    if (!plan) {
      skipped += 1;
      continue;
    }
    if (plan.shift) rfb.sendKey(DESKTOP_KEY.Shift[1], DESKTOP_KEY.Shift[0], true);
    rfb.sendKey(plan.keysym, plan.code, true);
    rfb.sendKey(plan.keysym, plan.code, false);
    if (plan.shift) rfb.sendKey(DESKTOP_KEY.Shift[1], DESKTOP_KEY.Shift[0], false);
  }
  return skipped;
}

export function clock(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
