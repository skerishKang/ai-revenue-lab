"""Exact server-owned isolated origin without weakening the product WSS pin."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.connector_gateway_worker_asgi_review import (
    REVIEW_WORKER_WSS_URL,
    exact_review_worker_wss_url,
)
from app.connector_gateway_first_pairing_tls_review import (
    CloudflareFirstPairingTlsTransportReview,
)
from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH

_STAGE_ORIGIN = "https://connector-acceptance.padiem.net"
_STAGE_URL = _STAGE_ORIGIN + CONNECTOR_GATEWAY_WSS_PATH
_STAGE = {
    "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "isolated-operator-acceptance-4139",
    "PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": _STAGE_ORIGIN,
    "PADIEM_CHAT_PUBLIC_BASE_URL": _STAGE_ORIGIN,
}


def _request(url):
    return SimpleNamespace(
        url=url, method="GET", headers={"upgrade": "websocket"},
        cf={"tlsVersion": "TLSv1.3"},
    )


def test_original_product_pin_retained_without_explicit_trusted_acceptance_origin():
    assert exact_review_worker_wss_url({}) == REVIEW_WORKER_WSS_URL
    assert REVIEW_WORKER_WSS_URL == "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH


def test_isolated_stage_requires_both_matching_server_settings():
    assert exact_review_worker_wss_url(_STAGE) == _STAGE_URL
    for modified in (
        {"PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.padiem.net"},
        {"PADIEM_CHAT_PUBLIC_BASE_URL": None},
        {"PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "production"},
        {"PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "enabled"},
        {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": "https://evil.example"},
        {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": "https://connector-acceptance.padiem.net.evil.example"},
        {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": "http://connector-acceptance.padiem.net"},
        {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": "https://connector-acceptance.padiem.net:443"},
        {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": "https://connector-acceptance.padiem.net/"},
        {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": "https://chat.padiem.net"},
        {"PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN": "https://connector-acceptance.padiem.net?x=1"},
    ):
        with pytest.raises(ValueError, match="origin"):
            exact_review_worker_wss_url({**_STAGE, **modified})


def test_stage_tls_guard_requires_exact_source_attested_request_url_and_path():
    review = CloudflareFirstPairingTlsTransportReview(
        incoming_worker_request=_request(_STAGE_URL),
        source_review_authorized=True,
        expected_url=exact_review_worker_wss_url(_STAGE),
    )
    assert review.permits_worker_upgrade() is True
    for bad in (
        REVIEW_WORKER_WSS_URL,
        _STAGE_URL + "?code=secret",
        _STAGE_URL + "#fragment",
        _STAGE_URL.replace("https://", "http://"),
        _STAGE_URL.replace("connector-acceptance", "connector-acceptance.evil"),
    ):
        review = CloudflareFirstPairingTlsTransportReview(
            incoming_worker_request=_request(bad),
            source_review_authorized=True,
            expected_url=exact_review_worker_wss_url(_STAGE),
        )
        assert review.permits_worker_upgrade() is False
    with pytest.raises(ValueError, match="unreviewed first pairing origin"):
        CloudflareFirstPairingTlsTransportReview(
            incoming_worker_request=_request(_STAGE_URL),
            source_review_authorized=True,
            expected_url="https://evil.example" + CONNECTOR_GATEWAY_WSS_PATH,
        )
