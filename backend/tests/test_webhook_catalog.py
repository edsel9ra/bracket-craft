"""Catálogo puro de webhooks (spec 047, T2): URL, secreto, cuerpo y firma."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.modules.notifications.catalog import NOTIFICATION_TYPES
from app.modules.webhooks import catalog


def test_catalog_constants_follow_the_spec():
    assert catalog.EVENT_TYPES == tuple(NOTIFICATION_TYPES)
    assert catalog.TEST_TYPE == "webhook_test"
    assert catalog.MAX_WEBHOOKS == 10
    assert catalog.MAX_ATTEMPTS == 6
    assert [int(delay.total_seconds() // 60) for delay in catalog.RETRY_DELAYS] == [1, 5, 15, 30, 120]


@pytest.mark.parametrize(
    "url",
    ["https://hooks.example.com/bc", "https://hooks.example.com:8443/a?b=1", "HTTPS://Hooks.Example.com/"],
)
def test_valid_urls_are_accepted(url):
    assert catalog.validate_url(url) == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/",
        "ftp://hooks.example.com/",
        "https://user:pass@hooks.example.com/",
        "https://user@hooks.example.com/",
        "https:///path",
        "https://",
        "https://hooks.example.com/" + "a" * 2048,
        "https://hooks.example.com/\nX: y",
        "https://hooks.example.com:0/",
        "",
    ],
)
def test_invalid_urls_are_rejected(url):
    with pytest.raises(ValueError):
        catalog.validate_url(url)


def test_audit_host_keeps_only_the_domain():
    assert catalog.audit_host("https://Hooks.Example.com:8443/secret/path?token=1") == "hooks.example.com"


def test_generated_secrets_are_random_and_long():
    first, second = catalog.generate_secret(), catalog.generate_secret()
    assert first != second
    assert first.startswith("whsec_") and len(first) >= 40


def test_body_serialization_is_canonical():
    body = {"type": "result_confirmed", "data": {"b": 1, "a": "ñ"}, "id": "x"}
    assert catalog.serialize_body(body) == b'{"data":{"a":"\xc3\xb1","b":1},"id":"x","type":"result_confirmed"}'


def test_signature_is_hmac_sha256_of_timestamp_and_body():
    body = catalog.serialize_body({"id": "d1"})
    expected = hmac.new(b"whsec_x", b"1700000000." + body, hashlib.sha256).hexdigest()
    assert catalog.sign("whsec_x", 1700000000, body) == f"v1={expected}"


def test_signature_headers():
    body = catalog.serialize_body({"id": "d1"})
    headers = catalog.signature_headers("whsec_x", event_type="result_confirmed", delivery_id="d1", timestamp=1700000000, body=body)
    assert headers == {
        "Content-Type": "application/json",
        "User-Agent": "BracketCraft-Webhooks/1",
        "X-BracketCraft-Event": "result_confirmed",
        "X-BracketCraft-Delivery": "d1",
        "X-BracketCraft-Timestamp": "1700000000",
        "X-BracketCraft-Signature": catalog.sign("whsec_x", 1700000000, body),
    }
    assert "whsec_x" not in json.dumps(headers)
