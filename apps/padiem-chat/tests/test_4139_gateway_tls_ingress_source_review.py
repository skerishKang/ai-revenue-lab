"""#4139 negative Cloudflare mTLS review; no live certificate or Worker route."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH
from app.connector_gateway_tls_ingress_source_review import (
    CLOUDFLARE_MTLS_PRODUCTION_ATTESTED,
    CLOUDFLARE_MTLS_WSS_PUBLIC_ENABLED,
    CloudflareMtlsIngressSourceReview,
)

_PIN = "a" * 64
_OTHER = "b" * 64
_URL = "https://chat.padiem.net" + CONNECTOR_GATEWAY_WSS_PATH
_SCOPE = {
    "type": "websocket", "scheme": "wss",
    "path": CONNECTOR_GATEWAY_WSS_PATH,
    "raw_path": CONNECTOR_GATEWAY_WSS_PATH.encode(),
    "query_string": b"",
}
_TLS = {
    "certPresented": "1", "certVerified": "SUCCESS",
    "certRevoked": "0", "certFingerprintSHA256": _PIN,
}


def _request(*, cf_tls=None, headers=None, url=_URL):
    return SimpleNamespace(
        url=url, headers={} if headers is None else headers,
        cf=SimpleNamespace(tlsClientAuth=dict(_TLS) if cf_tls is None else cf_tls),
    )


def _socket(*, headers=None, scope=None):
    return SimpleNamespace(
        scope=dict(_SCOPE) if scope is None else scope,
        headers={} if headers is None else headers,
    )


def _check(*, req=None, socket=None, pins=frozenset({_PIN})):
    port = CloudflareMtlsIngressSourceReview(
        incoming_worker_request=_request() if req is None else req,
        approved_sha256_fingerprints=pins,
        source_review_authorized=True,
    )
    return asyncio.run(port.verify(_socket() if socket is None else socket))


def test_source_only_provenance_never_enables_live_connector():
    assert CLOUDFLARE_MTLS_PRODUCTION_ATTESTED is False
    assert CLOUDFLARE_MTLS_WSS_PUBLIC_ENABLED is False
    source = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "CloudflareMtlsIngressSourceReview" not in source
    assert "connector_gateway_tls_ingress_source_review" not in source
    with pytest.raises(RuntimeError, match="not activated"):
        CloudflareMtlsIngressSourceReview(incoming_worker_request=_request())
    with pytest.raises(RuntimeError, match="not activated"):
        CloudflareMtlsIngressSourceReview(incoming_worker_request=_request(),
                                          source_review_authorized=1)


def test_synthetic_verified_nonrevoked_pinned_certificate_is_algorithmic_only():
    assert _check() is True
    assert _check(pins=frozenset()) is False
    assert _check(pins=frozenset({_OTHER})) is False


@pytest.mark.parametrize("changed", [
    {"certPresented": "0"},
    {"certPresented": True},
    {"certVerified": "NONE"},
    {"certVerified": "FAILED:self signed certificate"},
    {"certVerified": True},
    {"certRevoked": "1"},
    {"certRevoked": False},
    {"certFingerprintSHA256": _OTHER},
    {"certFingerprintSHA256": "A" * 64},
    {"certFingerprintSHA256": ""},
    {"certFingerprintSHA256": "a:" * 32},
])
def test_unverified_revoked_or_unpinned_certificate_fails_closed(changed):
    metadata = {**_TLS, **changed}
    assert _check(req=_request(cf_tls=metadata)) is False


@pytest.mark.parametrize("bad", [None, {}, {"tlsClientAuth": "SUCCESS"}, "SUCCESS"])
def test_missing_or_malformed_cf_certificate_metadata_fails_closed(bad):
    req = _request()
    req.cf = bad
    assert _check(req=req) is False


@pytest.mark.parametrize("headers", [
    {"cf-tls-client-auth": "SUCCESS"},
    {"x-forwarded-proto": "https", "cf-visitor": '{"scheme":"https"}'},
    {"cf-client-cert-sha256": _PIN},
    {"client-cert": ":signed-looking-data:"},
    {"origin": "https://chat.padiem.net"},
    {"cookie": "session=spoofed"},
    {"authorization": "Bearer synthetic"},
    {"sec-websocket-protocol": "pairing-code"},
])
def test_header_only_evidence_never_substitutes_for_edge_cf_verdict(headers):
    no_cf = _request(cf_tls={})
    no_cf.headers = headers
    assert _check(req=no_cf) is False
    assert _check(socket=_socket(headers=headers)) is False


@pytest.mark.parametrize("changes", [
    {"type": "http"}, {"scheme": "https"}, {"scheme": "ws"},
    {"path": "/unrelated"}, {"raw_path": b"/unrelated"},
    {"query_string": b"proof=secret"}, {"raw_path": None},
])
def test_mismatched_worker_websocket_scope_is_denied(changes):
    assert _check(socket=_socket(scope={**_SCOPE, **changes})) is False


def test_missing_request_and_ambiguous_origin_refused():
    assert _check(req=SimpleNamespace()) is False
    assert _check(req=_request(url="https://chat.padiem.net:443" +
                                CONNECTOR_GATEWAY_WSS_PATH)) is False
    assert _check(req=_request(url=_URL + "?proof=bad")) is False


@pytest.mark.parametrize("pins", [
    ["a" * 64], "a" * 64, frozenset({"A" * 64}),
    frozenset({"b" * 63}), frozenset({"a" * 64, ""}),
    frozenset(str(i).zfill(64) for i in range(33)),
])
def test_operator_pin_input_invalid_is_refused(pins):
    with pytest.raises(ValueError, match="fingerprint set required"):
        CloudflareMtlsIngressSourceReview(
            incoming_worker_request=_request(),
            approved_sha256_fingerprints=pins,
            source_review_authorized=True,
        )
