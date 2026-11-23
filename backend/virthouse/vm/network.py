"""Assign a /24 to a VM from the host's first subnet.

`system.yaml` stores only `subnet_base`. The next VM uses the following /24:
ordinal 0 keeps that subnet, ordinal 1 adds 1 to the third octet, and so on.
The gateway is host address .1 and the guest address is .2.
"""

from __future__ import annotations

import ipaddress

from virthouse.vm.errors import VmError


def assign_subnet(subnet_base: str, ordinal: int) -> tuple[str, str, str]:
    """Return `(subnet, gateway, guest_ip)` for this ordinal."""
    if ordinal < 0:
        raise VmError(f"subnet ordinal must be >= 0, got {ordinal}")
    try:
        base = ipaddress.ip_network(subnet_base, strict=False)
    except ValueError as exc:
        raise VmError(f"invalid subnet_base: {subnet_base}") from exc
    if base.prefixlen != 24 or not isinstance(base.network_address, ipaddress.IPv4Address):
        raise VmError(f"subnet_base must be an IPv4 /24, got {subnet_base}")

    shifted = int(base.network_address) + ordinal * 256
    if shifted > 0xFFFFFFFF:
        raise VmError(f"no free subnet after {subnet_base}")
    network = ipaddress.ip_network((shifted, 24))
    gateway = str(network.network_address + 1)
    guest = str(network.network_address + 2)
    return str(network), gateway, guest


def next_ordinal(subnet_base: str, used_subnets: set[str]) -> int:
    """Smallest ordinal whose subnet is not already assigned."""
    for ordinal in range(256):
        subnet, _, _ = assign_subnet(subnet_base, ordinal)
        if subnet not in used_subnets:
            return ordinal
    raise VmError(f"no free subnet after {subnet_base}")
