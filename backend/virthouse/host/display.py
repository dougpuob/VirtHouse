"""The latest JPEG of this computer's desktop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from virthouse.host.input import normalize_input
from virthouse.host.vnc import HostVnc

CAPTURE = Path(__file__).with_name("capture.py")
IDLE_SEC = 3
MAX_FRAME = 20_000_000


def read_exact(stream, size: int) -> bytes | None:
    """Read `size` bytes, or None when the stream ends early."""
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frames(stream, on_frame) -> None:
    """Read length-prefixed JPEGs until the stream closes."""
    while True:
        header = read_exact(stream, 4)
        if header is None:
            return
        length = int.from_bytes(header, "big")
        if length <= 0 or length > MAX_FRAME:
            raise ValueError(f"bad frame length {length}")
        payload = read_exact(stream, length)
        if payload is None:
            return
        on_frame(payload)


class HostDisplay:
    """Start a desktop capture while something is asking for frames."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._problem = "Opening the host display."
        self._last = 0.0
        self._failed_at = 0.0
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._idle_stop = threading.Event()
        self._idle = threading.Thread(target=self._watch_idle, name="host-display-idle", daemon=True)
        self._idle.start()
        self._vnc = HostVnc(self)

    @property
    def vnc_port(self) -> int:
        return self._vnc.port

    def send(self, event: dict) -> None:
        """Forward one pointer or keyboard event while the picture is open."""
        command = normalize_input(event)
        if command is None:
            return
        line = (json.dumps(command) + "\n").encode()
        with self._lock:
            self._last = time.monotonic()
            proc = self._proc
            dead = proc is None or proc.poll() is not None
            if dead and time.monotonic() - self._failed_at >= 2:
                self._start_locked()
                proc = self._proc
            if proc is None or proc.stdin is None or proc.poll() is not None:
                return
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (OSError, ValueError):
                return

    def frame(self) -> bytes | None:
        with self._lock:
            self._last = time.monotonic()
            proc = self._proc
            dead = proc is None or proc.poll() is not None
            if dead and time.monotonic() - self._failed_at >= 2:
                self._start_locked()
            return self._jpeg

    def problem(self) -> str:
        with self._lock:
            if self._jpeg is not None:
                return ""
            return self._problem

    def close(self) -> None:
        self._vnc.close()
        self._idle_stop.set()
        with self._lock:
            self._stop_locked()
        reader = self._reader
        if reader is not None:
            reader.join(timeout=2)

    def _start_locked(self) -> None:
        python = "/usr/bin/python3"
        if not Path(python).is_file():
            python = sys.executable
        try:
            proc = subprocess.Popen(
                [python, str(CAPTURE)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
            )
        except OSError as exc:
            self._problem = str(exc) or "The host display is not available."
            self._failed_at = time.monotonic()
            return
        self._proc = proc
        self._problem = "Opening the host display."
        self._reader = threading.Thread(target=self._read, args=(proc,), name="host-display", daemon=True)
        self._reader.start()

    def _stop_locked(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _read(self, proc: subprocess.Popen) -> None:
        stderr = b""

        def keep_error() -> None:
            nonlocal stderr
            if proc.stderr is None:
                return
            stderr = proc.stderr.read()

        drain = threading.Thread(target=keep_error, daemon=True)
        drain.start()
        try:
            assert proc.stdout is not None
            read_frames(proc.stdout, self._store)
        except Exception as exc:
            with self._lock:
                if self._jpeg is None:
                    self._problem = str(exc) or "The host display is not available."
                    self._failed_at = time.monotonic()
        drain.join(timeout=1)
        code = proc.poll()
        with self._lock:
            if self._proc is proc:
                self._proc = None
            if self._jpeg is None:
                message = stderr.decode("utf-8", "replace").strip()
                self._problem = message or f"The host display stopped ({code})."
                self._failed_at = time.monotonic()

    def _store(self, payload: bytes) -> None:
        with self._lock:
            self._jpeg = payload
            self._problem = ""

    def _watch_idle(self) -> None:
        while not self._idle_stop.wait(0.5):
            with self._lock:
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    continue
                if self._last and time.monotonic() - self._last > IDLE_SEC:
                    self._stop_locked()
