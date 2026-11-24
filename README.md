# VirtHouse
QEMU multi-instance management system with WebUI, RESTful API, ephemeral overlays, and device passthrough.


```
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export VIRTHOUSE_PORT=8080
.venv/bin/python -m virthouse
```