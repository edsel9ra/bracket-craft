"""Protección de red de webhooks (spec 047, T2, RF-009)."""

from __future__ import annotations

import ipaddress

import pytest

from app.modules.webhooks import network


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1", "172.16.0.1", "192.168.1.1", "127.0.0.1", "169.254.169.254", "169.254.1.1",
        "100.64.0.1", "224.0.0.1", "240.0.0.1", "0.0.0.0", "255.255.255.255", "192.0.0.1", "198.18.0.1",
        "::1", "::", "fe80::1", "fc00::1", "fd00:ec2::254", "ff02::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
        "64:ff9b::7f00:1", "2001:db8::1",
    ],
)
def test_internal_addresses_are_rejected(address):
    assert network.address_allowed(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(address):
    assert network.address_allowed(ipaddress.ip_address(address)) is True


async def test_resolve_target_requires_every_address_to_be_public():
    async def resolver(host, port):
        return {"good.test": ["93.184.216.34", "8.8.8.8"], "mixed.test": ["93.184.216.34", "10.0.0.1"]}.get(host, [])

    assert await network.resolve_target("good.test", 443, resolver) == ["93.184.216.34", "8.8.8.8"]
    for host in ("mixed.test", "missing.test"):
        with pytest.raises(network.TargetRejected):
            await network.resolve_target(host, 443, resolver)


async def test_resolver_errors_are_rejections():
    async def resolver(host, port):
        raise OSError("dns down")

    with pytest.raises(network.TargetRejected):
        await network.resolve_target("good.test", 443, resolver)


async def test_literal_internal_ip_is_rejected_without_resolution():
    async def resolver(host, port):
        raise AssertionError("no debe resolverse")

    with pytest.raises(network.TargetRejected):
        await network.resolve_target("127.0.0.1", 443, resolver)
