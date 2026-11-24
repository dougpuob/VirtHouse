"""Pointer and keyboard events for this computer's desktop."""

from __future__ import annotations

_CODES = {
    "Enter": 0xFF0D,
    "Backspace": 0xFF08,
    "Tab": 0xFF09,
    "Escape": 0xFF1B,
    "ArrowLeft": 0xFF51,
    "ArrowUp": 0xFF52,
    "ArrowRight": 0xFF53,
    "ArrowDown": 0xFF54,
    "Delete": 0xFFFF,
    "Home": 0xFF50,
    "End": 0xFF57,
    "PageUp": 0xFF55,
    "PageDown": 0xFF56,
    "ShiftLeft": 0xFFE1,
    "ShiftRight": 0xFFE2,
    "ControlLeft": 0xFFE3,
    "ControlRight": 0xFFE4,
    "AltLeft": 0xFFE9,
    "AltRight": 0xFFEA,
    "MetaLeft": 0xFFEB,
    "MetaRight": 0xFFEC,
    "Space": 0x0020,
    "CapsLock": 0xFFE5,
}


def keysym_for(code: str, key: str) -> int | None:
    """Return an X keysym for a browser key, or None when it cannot be sent."""
    if code in _CODES:
        return _CODES[code]
    if code.startswith("F") and code[1:].isdigit():
        number = int(code[1:])
        if 1 <= number <= 12:
            return 0xFFBE + number - 1
    if len(key) == 1 and ord(key) <= 0xFF:
        return ord(key)
    return None


def normalize_input(body: dict) -> dict | None:
    """Return a command the capture process understands, or None to ignore it."""
    op = body.get("op")
    try:
        if op == "move":
            return {"op": "move", "x": float(body["x"]), "y": float(body["y"])}
        if op == "button":
            button = int(body["button"])
            if button not in (1, 2, 3):
                return None
            return {"op": "button", "button": button, "down": bool(body["down"])}
        if op == "key":
            if body.get("keysym") is not None and not body.get("code"):
                keysym = int(body["keysym"])
                if not 0 <= keysym <= 0xFFFFFFFF:
                    return None
                return {"op": "key", "keysym": keysym, "down": bool(body["down"])}
            keysym = keysym_for(str(body.get("code") or ""), str(body.get("key") or ""))
            if keysym is None:
                return None
            return {"op": "key", "keysym": keysym, "down": bool(body["down"])}
        if op == "wheel":
            return {"op": "wheel", "dx": float(body.get("dx") or 0), "dy": float(body.get("dy") or 0)}
    except (KeyError, TypeError, ValueError):
        return None
    return None
