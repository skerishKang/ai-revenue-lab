"""#4139 FIRST pairing TLS transport: negative contract, no live ingress."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from app.connector_gateway_first_pairing_tls_review import (
    FIRST_PAIRING_TLS_ONLY_PRODUCTION_WIRED,
    FIRST_PAIRING_WSS_PUBLIC_MOUNTED,
    CloudflareFirstPairingTlsTransportReview,
)
from app.connector_gateway_tls_ingress_source_review import (
    CloudflareMtlsIngressSourceReview,
)

URL = "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH
SCOPE = {
    "type": "websocket", "scheme": "wss",
    "path": CONNECTOR_GATEWAY_WSS_PATH,
    "raw_path": CONNECTOR_GATEWAY_WSS_PATH.encode("ascii"),
    "query_string": b"",
}


_CF_UNSET = object()


def _request(*, tls="TLSv1.3", url=URL, headers=None, cf=_CF_UNSET, method="GET"):
    return SimpleNamespace(
        url=url, method=method,
        headers={} if headers is None else headers,
        cf={"tlsVersion": tls} if cf is _CF_UNSET else cf,
    )


def _ws(*, scope=None, headers=None):
    return SimpleNamespace(
        scope=dict(SCOPE) if scope is None else scope,
        headers={} if headers is None else headers,
    )


def _verify(request=None, ws=None):
    verifier = CloudflareFirstPairingTlsTransportReview(
        incoming_worker_request=_request() if request is None else request,
        source_review_authorized=True,
    )
    return asyncio.run(verifier.verify(_ws() if ws is None else ws))


def test_first_pairing_makes_no_live_claim_and_no_public_worker_mount():
    assert FIRST_PAIRING_TLS_ONLY_PRODUCTION_WIRED is False
    assert FIRST_PAIRING_WSS_PUBLIC_MOUNTED is False
    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text("utf-8")
    app_factory = (Path(__file__).resolve().parents[1] / "app" / "app_factory.py").read_text("utf-8")
    assert "CloudflareFirstPairingTlsTransportReview" not in worker
    assert "CloudflareFirstPairingTlsTransportReview" not in app_factory
    with pytest.raises(RuntimeError, match="not activated"):
        CloudflareFirstPairingTlsTransportReview()
    with pytest.raises(RuntimeError, match="not activated"):
        CloudflareFirstPairingTlsTransportReview(
            incoming_worker_request=_request(), source_review_authorized=1,
        )


@pytest.mark.parametrize("tls", ["TLSv1.2", "TLSv1.3"])
def test_tls_first_pairing_permits_only_secure_transport_not_client_identity(tls):
    request = _request(tls=tls, cf={"tlsVersion": tls, "tlsClientAuth": None})
    assert _verify(request) is True  # only a transport admission
    # The old mTLS adapter is intentionally NOT weakened or bypassed.
    mtls = CloudflareMtlsIngressSourceReview(
        incoming_worker_request=request,
        approved_sha256_fingerprints=frozenset({"a" * 64}),
        source_review_authorized=True,
    )
    assert asyncio.run(mtls.verify(_ws())) is False


@pytest.mark.parametrize("tls", [
    None, "", "TLSv1", "TLSv1.0", "TLSv1.1", "SSLv3", "tlsv1.3",
    "TLSv1.4", "TLSv1.3, TLSv1.2", False, True, ["TLSv1.3"],
])
def test_missing_legacy_or_ambiguous_cloudflare_edge_tls_denied(tls):
    assert _verify(_request(tls=tls)) is False


@pytest.mark.parametrize("cf", [None, {}, "TLSv1.3", {"tlsVersion": None}])
def test_no_runtime_edge_cf_metadata_refused(cf):
    assert _verify(_request(cf=cf)) is False


@pytest.mark.parametrize("headers", [
    {"origin": "https://chat.padiem.net"},
    {"cookie": "session=fake"},
    {"authorization": "Bearer fake"},
    {"client-cert": "bogus"},
    {"cf-client-cert-sha256": "a" * 64},
    {"sec-websocket-protocol": "credential"},
    {"cf-tls-client-auth": "SUCCESS"},
])
def test_http_headers_cannot_assert_tls_or_owner_identity(headers):
    assert _verify(_request(headers=headers)) is False
    assert _verify(ws=_ws(headers=headers)) is False


@pytest.mark.parametrize("url", [
    "http://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH,
    "wss://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH,
    "https://chat.padiem.net:443" + CONNECTOR_GATEWAY_WSS_PATH,
    "https://chat.padiem.net.evil.test" + CONNECTOR_GATEWAY_WSS_PATH,
    URL + "?challenge=leak", URL + "#pair",
    URL.replace("/session", "/%73ession"),
])
def test_wrong_origin_and_query_denied(url):
    assert _verify(_request(url=url)) is False


@pytest.mark.parametrize("changed", [
    {"type": "http"},
    {"scheme": "https"}, {"scheme": "ws"},
    {"path": "/other"},
    {"raw_path": b"/api/claw/connector/gateway/%73ession"},
    {"raw_path": None},
    {"query_string": b"device=forged"},
])
def test_wrong_websocket_scope_denied(changed):
    assert _verify(ws=_ws(scope={**SCOPE, **changed})) is False


def test_header_spoofing_does_not_repair_missing_tls_metadata():
    req = _request(
        cf={}, headers={"x-forwarded-proto": "https", "cf-tls-client-auth": "SUCCESS"},
    )
    assert _verify(req) is False
    assert _verify(SimpleNamespace(url=URL, headers={})) is False


def test_request_and_websocket_properties_fail_closed():
    assert _verify(SimpleNamespace()) is False
    assert _verify(ws=SimpleNamespace()) is False
    assert _verify(ws=_ws(scope="websocket")) is False


@pytest.mark.parametrize("edge_headers", [
    {"cf-visitor": '{"scheme":"https"}'},
    {"x-forwarded-proto": "https"},
    {"cf-visitor": '{"scheme":"https"}', "x-forwarded-proto": "https"},
    {"cf-ray": "synthetic-ray", "cf-connecting-ip": "192.0.2.1"},
])
def test_cloudflare_added_headers_are_ignored_not_identity(edge_headers):
    """Edge-generated HTTP headers must not deny valid TLS or establish trust."""
    assert _verify(_request(headers=edge_headers)) is True
    assert _verify(ws=_ws(headers=edge_headers)) is True
    missing_cf = _request(headers=edge_headers, cf={})
    assert _verify(missing_cf) is False
    downgraded_cf = _request(headers=edge_headers, tls="TLSv1.0")
    assert _verify(downgraded_cf) is False
