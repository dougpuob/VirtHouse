"""Write JPEGs of this computer's desktop to stdout, and apply input from stdin.

GNOME on Wayland does not allow a Screenshot call from this process. Mutter's
screencast API does, and its remote-desktop session accepts pointer and
keyboard events for that same stream. Each frame is a 4-byte big-endian length
and then that many JPEG bytes. Stdin is JSON lines (`move`, `button`, `key`,
`wheel`). The process stops when stdin closes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading


def active_connectors(logical_monitors: list) -> list[str]:
    """Return connector names, primary display first."""
    primary: list[str] = []
    rest: list[str] = []
    for monitor in logical_monitors:
        names = [str(entry[0]) for entry in monitor[5]]
        if monitor[4]:
            primary.extend(names)
        else:
            rest.extend(names)
    return primary + rest


def object_serial(node_id: int) -> str:
    """Return the PipeWire object serial for a node id."""
    raw = subprocess.check_output(["pw-dump"], text=True)
    for obj in json.loads(raw):
        if obj.get("id") != node_id:
            continue
        serial = (obj.get("info") or {}).get("props", {}).get("object.serial")
        if serial is None:
            break
        return str(serial)
    raise RuntimeError(f"PipeWire node {node_id} has no object serial")


def main() -> int:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    DBusGMainLoop(set_as_default=True)
    Gst.init(None)
    bus = dbus.SessionBus()
    screen_cast = dbus.Interface(
        bus.get_object("org.gnome.Mutter.ScreenCast", "/org/gnome/Mutter/ScreenCast"),
        "org.gnome.Mutter.ScreenCast",
    )
    display = dbus.Interface(
        bus.get_object("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig"),
        "org.gnome.Mutter.DisplayConfig",
    )
    _serial, _monitors, logical, _props = display.GetCurrentState()
    connectors = active_connectors(logical)
    if not connectors:
        print("No host display is connected.", file=sys.stderr)
        return 1
    remote = dbus.Interface(
        bus.get_object("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop"),
        "org.gnome.Mutter.RemoteDesktop",
    )
    desktop_path = remote.CreateSession()
    desktop_obj = bus.get_object("org.gnome.Mutter.RemoteDesktop", desktop_path)
    desktop = dbus.Interface(desktop_obj, "org.gnome.Mutter.RemoteDesktop.Session")
    session_id = dbus.Interface(desktop_obj, "org.freedesktop.DBus.Properties").Get(
        "org.gnome.Mutter.RemoteDesktop.Session",
        "SessionId",
    )
    session_path = screen_cast.CreateSession(dbus.Dictionary({
        "remote-desktop-session-id": dbus.String(session_id),
    }, signature="sv"))
    session = dbus.Interface(
        bus.get_object("org.gnome.Mutter.ScreenCast", session_path),
        "org.gnome.Mutter.ScreenCast.Session",
    )
    properties = dbus.Dictionary({"cursor-mode": dbus.UInt32(1)}, signature="sv")
    stream_path = str(session.RecordMonitor(connectors[0], properties))
    node: dict[str, int] = {}
    wait = GLib.MainLoop()

    def on_added(node_id: int) -> None:
        node["id"] = int(node_id)
        wait.quit()

    bus.add_signal_receiver(
        on_added,
        signal_name="PipeWireStreamAdded",
        dbus_interface="org.gnome.Mutter.ScreenCast.Stream",
        path=str(stream_path),
    )
    GLib.timeout_add(3000, wait.quit)

    def apply_input(text: str) -> bool:
        try:
            event = json.loads(text)
            op = event.get("op")
            if op == "move":
                desktop.NotifyPointerMotionAbsolute(stream_path, dbus.Double(event["x"]), dbus.Double(event["y"]))
            elif op == "button":
                # Mutter wants evdev codes: 0x110 left, 0x111 right, 0x112 middle.
                button = {1: 0x110, 2: 0x112, 3: 0x111}.get(int(event["button"]))
                if button is None:
                    return False
                desktop.NotifyPointerButton(dbus.Int32(button), dbus.Boolean(event["down"]))
            elif op == "key":
                desktop.NotifyKeyboardKeysym(dbus.UInt32(event["keysym"]), dbus.Boolean(event["down"]))
            elif op == "wheel":
                desktop.NotifyPointerAxis(dbus.Double(event.get("dx") or 0), dbus.Double(event.get("dy") or 0), dbus.UInt32(0))
        except Exception as exc:
            print(f"host input: {exc}", file=sys.stderr)
        return False

    try:
        desktop.Start()
        if "id" not in node:
            wait.run()
        if "id" not in node:
            print("The host display did not open a stream.", file=sys.stderr)
            return 1
        serial = object_serial(node["id"])
        pipeline = Gst.parse_launch(
            f"pipewiresrc target-object={serial} ! videoconvert ! jpegenc quality=60 "
            "! appsink name=sink emit-signals=true max-buffers=2 drop=true sync=false enable-last-sample=false"
        )
        loop = GLib.MainLoop()

        def on_sample(sink):
            sample = sink.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.ERROR
            buffer = sample.get_buffer()
            ok, info = buffer.map(Gst.MapFlags.READ)
            try:
                if not ok:
                    return Gst.FlowReturn.ERROR
                payload = bytes(info.data)
            finally:
                if ok:
                    buffer.unmap(info)
            try:
                sys.stdout.buffer.write(len(payload).to_bytes(4, "big"))
                sys.stdout.buffer.write(payload)
                sys.stdout.buffer.flush()
            except BrokenPipeError:
                GLib.idle_add(loop.quit)
            return Gst.FlowReturn.OK

        pipeline.get_by_name("sink").connect("new-sample", on_sample)
        bus_gst = pipeline.get_bus()
        bus_gst.add_signal_watch()

        def on_message(_bus, message):
            if message.type == Gst.MessageType.ERROR:
                error, _debug = message.parse_error()
                print(error.message, file=sys.stderr)
                loop.quit()

        bus_gst.connect("message", on_message)
        pipeline.set_state(Gst.State.PLAYING)

        def watch_stdin():
            try:
                for line in sys.stdin:
                    text = line.strip()
                    if text:
                        GLib.idle_add(apply_input, text)
            finally:
                GLib.idle_add(loop.quit)

        threading.Thread(target=watch_stdin, daemon=True).start()
        loop.run()
        pipeline.set_state(Gst.State.NULL)
        return 0
    finally:
        try:
            desktop.Stop()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc) or "The host display is not available.", file=sys.stderr)
        raise SystemExit(1) from exc
