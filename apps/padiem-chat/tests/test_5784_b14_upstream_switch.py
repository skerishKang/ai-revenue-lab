"""#5784 PR-2: one variable chooses whether Chat calls the B14 Worker or COM2 B14.

Default is the Service Binding and composes exactly what this Worker has always
composed. The HTTPS side reuses the same caller proof over the same exact body,
pins the origin and path allowlist, and refuses a half-flipped switch instead of
guessing which upstream the deployment meant.
"""

from __future__ import annotations

import pytest

from app.b14_service_proof import service_proof_headers
from app.b14_upstream_composition import (
    B14_UPSTREAM_PATHS,
    B14_UPSTREAM_POST_PATHS,
    B14_UPSTREAM_READ_PATHS,
    compose_b14_transports,
)
from app.config import ConfigError, Settings
from app.worker_config import settings_from_worker_bindings
from padiem_ai_core.b14_upstream import B14HttpsPostJson, B14HttpsTransport

TUNNEL_ORIGIN = "https://b14.padiem.net"


class _BindingService:
    def __init__(self, binding, proof_secret):
        self.binding = binding
        self.proof_secret = proof_secret


class _BindingStream:
    def __init__(self, binding, proof_secret):
        self.binding = binding


def _client():  # a stand-in for the Worker's fetch-backed AsyncClient
    return object()


def _compose(*, mode="binding", origin="https://b14.internal", binding=object(), secret=None):
    return compose_b14_transports(
        upstream_mode=mode,
        origin=origin,
        binding=binding,
        proof_secret=secret,
        service_binding_factory=_BindingService,
        stream_binding_factory=_BindingStream,
        https_client_factory=_client,
    )


def test_default_composition_is_the_two_binding_transports() -> None:
    service, stream = _compose()
    assert isinstance(service, _BindingService) and isinstance(stream, _BindingStream)
    assert service.binding is not None


def test_binding_mode_without_a_binding_still_composes_nothing() -> None:
    assert _compose(binding=None) == (None, None)


def test_https_mode_composes_the_signed_http_pair() -> None:
    service, stream = _compose(mode="https", origin=TUNNEL_ORIGIN)
    assert isinstance(stream, B14HttpsTransport)
    assert isinstance(service, B14HttpsPostJson)
    assert stream.origin == TUNNEL_ORIGIN
    assert stream._allowed_paths == B14_UPSTREAM_PATHS


def test_https_mode_never_falls_back_to_the_binding_it_just_turned_off() -> None:
    with pytest.raises(ValueError, match="b14_upstream_url_required"):
        _compose(mode="https", origin=None)


def test_the_allowlist_covers_execution_and_the_two_authority_reads() -> None:
    assert B14_UPSTREAM_POST_PATHS and B14_UPSTREAM_READ_PATHS
    assert "/api/pilot/models" in B14_UPSTREAM_PATHS
    assert "/api/pilot/provider-readiness" in B14_UPSTREAM_PATHS


def test_https_and_binding_sign_the_same_exact_body_the_same_way() -> None:
    body = b'{"model":"m","messages":[{"role":"user","content":"\xec\x95\x88\xeb\x85\x95"}]}'
    secret = "a-deployment-proof-secret-0123456789ab"
    expected = service_proof_headers(secret, body)
    _, stream = _compose(mode="https", origin=TUNNEL_ORIGIN, secret=secret)
    assert stream._headers_for_body(body) == expected
    assert set(expected) == {"X-Padiem-B14-Proof", "X-Padiem-B14-Time"}


def test_an_unconfigured_proof_still_sends_no_headers() -> None:
    _, stream = _compose(mode="https", origin=TUNNEL_ORIGIN, secret=None)
    assert stream._headers_for_body(b"{}") == {}


# --- the switch as a deployment setting -------------------------------------


def test_settings_default_to_the_binding_and_keep_today_behaviour() -> None:
    settings = Settings.from_values(runtime_mode="b14", b14_base_url="https://b14.internal")
    assert settings.b14_upstream_mode == "binding"
    assert settings.b14_base_url == "https://b14.internal"


def test_the_switch_moves_the_origin_and_nothing_else() -> None:
    settings = Settings.from_values(
        runtime_mode="b14",
        b14_upstream_mode="https",
        b14_upstream_url=TUNNEL_ORIGIN,
    )
    assert settings.b14_upstream_mode == "https"
    assert settings.b14_base_url == TUNNEL_ORIGIN
    assert settings.timeout_seconds == Settings().timeout_seconds


def test_the_two_names_are_read_from_worker_bindings() -> None:
    settings = settings_from_worker_bindings({
        "PADIEM_CHAT_RUNTIME_MODE": "b14",
        "B14_UPSTREAM_MODE": "https",
        "B14_UPSTREAM_URL": TUNNEL_ORIGIN,
    })
    assert settings.b14_upstream_mode == "https"
    assert settings.b14_base_url == TUNNEL_ORIGIN


@pytest.mark.parametrize(
    "values,reason",
    [
        ({"B14_UPSTREAM_MODE": "tls"}, "b14_upstream_mode_invalid"),
        ({"B14_UPSTREAM_MODE": "https"}, "b14_upstream_url_required"),
        ({"B14_UPSTREAM_MODE": "https", "B14_UPSTREAM_URL": "http://b14.example.com"}, "b14_upstream_url_scheme_invalid"),
        ({"B14_UPSTREAM_URL": TUNNEL_ORIGIN}, "b14_upstream_url_ignored_in_binding_mode"),
        (
            {
                "B14_UPSTREAM_MODE": "https",
                "B14_UPSTREAM_URL": TUNNEL_ORIGIN,
                "PADIEM_CHAT_B14_BASE_URL": "https://b14.internal",
            },
            "conflicts",
        ),
    ],
)
def test_a_half_applied_switch_refuses_to_start(values, reason) -> None:
    bindings = {"PADIEM_CHAT_RUNTIME_MODE": "b14", **values}
    with pytest.raises(ConfigError) as error:
        settings_from_worker_bindings(bindings)
    assert reason in str(error.value)
