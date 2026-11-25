"""Protección de red de webhooks (spec 047, RF-009): solo destinos públicos."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[Iterable[str]]]

_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "192.0.0.0/24",
        "198.18.0.0/15",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2002::/16",
        "2001::/32",
        "fd00:ec2::/32",
    )
)


class TargetRejected(Exception):
    """El destino no resuelve o resuelve a una dirección no pública."""


def address_allowed(address: Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped or address.sixtofour
        if mapped is not None:
            return address_allowed(mapped)
    if any(address in network for network in _BLOCKED_NETWORKS if network.version == address.version):
        return False
    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def resolve_target(host: str, port: int, resolver: Resolver = system_resolver) -> list[str]:
    """Resuelve ``host`` y devuelve sus IP solo si todas son públicas."""
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not address_allowed(literal):
            raise TargetRejected
        return [str(literal)]
    try:
        raw = list(await resolver(host, port))
    except (OSError, UnicodeError) as error:
        raise TargetRejected from error
    addresses: list[str] = []
    for value in raw:
        try:
            address = ipaddress.ip_address(value.split("%", 1)[0])
        except ValueError as error:
            raise TargetRejected from error
        if not address_allowed(address):
            raise TargetRejected
        if str(address) not in addresses:
            addresses.append(str(address))
    if not addresses:
        raise TargetRejected
    return addresses
