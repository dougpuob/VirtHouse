"""Errors raised while starting or stopping a VM."""


class VmError(Exception):
    """The request cannot be carried out. The message is safe to return to the caller."""


class VmNotFound(VmError):
    """No VM with this id is known to the backend."""
