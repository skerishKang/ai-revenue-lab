"""B14 upstream mode resolution contracts for #5784 PR-2.

The switch is one variable and the default must be invisible: a deployment that
does not set it keeps the binding origin, the same transports and the same
headers it has today. These tests pin the default, every half-flipped state that
must refuse to start, and the rule that the HTTPS side still signs the exact body
and still cannot be steered off the allowlist.
"""

from __future__ import annotations

import pytest

from padiem_ai_core import b14_upstream as up

BINDING_URL = "https://b14.padiem.net"
ALLOWED = frozenset({"/api/pilot/v1/chat/completions"})


def test_default_is_binding_and_carries_the_binding_origin() -> None:
    resolved = up.resolve_b14_upstream({})
    assert resolved.mode == up.MODE_BINDING
    assert resolved.origin == up.BINDING_ORIGIN
    assert resolved.uses_service_binding and not resolved.uses_https


def test_explicit_binding_mode_is_the_same_as_the_default() -> None:
    assert up.resolve_b14_upstream({up.UPSTREAM_MODE_ENV: "binding"}) == up.resolve_b14_upstream({})


def test_https_mode_resolves_the_validated_origin_only() -> None:
    resolved = up.resolve_b14_upstream(
        {up.UPSTREAM_MODE_ENV: "https", up.UPSTREAM_URL_ENV: BINDING_URL + "/"}
    )
    assert resolved.origin == BINDING_URL
    assert resolved.uses_https


@pytest.mark.parametrize(
    "environ,code",
    [
        ({up.UPSTREAM_MODE_ENV: "HTTPS ", up.UPSTREAM_URL_ENV: BINDING_URL}, None),
        ({up.UPSTREAM_MODE_ENV: "http", up.UPSTREAM_URL_ENV: BINDING_URL}, "b14_upstream_mode_invalid"),
        ({up.UPSTREAM_MODE_ENV: "https"}, "b14_upstream_url_required"),
        ({up.UPSTREAM_MODE_ENV: "https", up.UPSTREAM_URL_ENV: "http://b14.example.com"}, "b14_upstream_url_scheme_invalid"),
        ({up.UPSTREAM_MODE_ENV: "https", up.UPSTREAM_URL_ENV: "https://user@b14.example.com"}, "b14_upstream_url_credentials_forbidden"),
        ({up.UPSTREAM_MODE_ENV: "https", up.UPSTREAM_URL_ENV: "https://b14.example.com?x=1"}, "b14_upstream_url_query_forbidden"),
        ({up.UPSTREAM_MODE_ENV: "https", up.UPSTREAM_URL_ENV: "https://b14.example.com/v1"}, "b14_upstream_url_path_forbidden"),
        ({up.UPSTREAM_MODE_ENV: "https", up.UPSTREAM_URL_ENV: up.BINDING_ORIGIN}, "b14_upstream_url_reserved_origin"),
        # A URL beside the binding mode is a half-flipped switch, not a hint.
        ({up.UPSTREAM_URL_ENV: BINDING_URL}, "b14_upstream_url_ignored_in_binding_mode"),
    ],
)
def test_the_switch_refuses_every_state_it_must_not_guess(environ, code) -> None:
    if code is None:
        assert up.resolve_b14_upstream(environ).uses_https
        return
    with pytest.raises(up.B14UpstreamConfigError) as error:
        up.resolve_b14_upstream(environ)
    assert error.value.code == code


def test_the_switch_never_leaves_a_selected_mode_behind() -> None:
    """Flipping the variable is the whole rollback: no state, no cache."""
    first = up.resolve_b14_upstream({up.UPSTREAM_MODE_ENV: "https", up.UPSTREAM_URL_ENV: BINDING_URL})
    second = up.resolve_b14_upstream({})
    assert first.uses_https and second.uses_service_binding


class _RecordingClient:
    def __init__(self):
        self.sent = []

    def build_request(self, method, url, headers=None, content=None):
        return {"method": method, "url": url, "headers": dict(headers or {}), "content": content}

    async def send(self, request, stream=False):
        self.sent.append(request)
        response = _Response(request["method"], request["url"])
        return response

    async def aclose(self):
        self.closed = True


class _Response:
    def __init__(self, method, url):
        self.status_code = 200
        self.headers = {}
        self.request = None
        self._url = url

    async def aread(self):
        return b'{"ok": true}'

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_https_transport_signs_the_exact_body_and_keeps_the_allowlist() -> None:
    import httpx

    seen: list[bytes] = []

    def headers_for_body(body: bytes):
        seen.append(body)
        return {"X-Padiem-B14-Proof": "proof-over-this-body"}

    client = _RecordingClient()
    transport = up.B14HttpsTransport(
        origin=BINDING_URL,
        allowed_paths=ALLOWED,
        headers_for_body=headers_for_body,
        correlation_headers=lambda: {"X-Request-Id": "req_local_1"},
        client=client,
    )
    body = b'{"model":"m"}'
    response = await transport.handle_async_request(
        httpx.Request("POST", BINDING_URL + "/api/pilot/v1/chat/completions", content=body)
    )
    assert response.status_code == 200
    assert seen == [body]
    sent = client.sent[0]
    assert sent["headers"]["X-Padiem-B14-Proof"] == "proof-over-this-body"
    assert sent["headers"]["X-Request-Id"] == "req_local_1"
    assert sent["content"] == body


@pytest.mark.asyncio
async def test_https_transport_refuses_targets_it_did_not_choose() -> None:
    import httpx

    transport = up.B14HttpsTransport(origin=BINDING_URL, allowed_paths=ALLOWED)
    for url, fragment in (
        ("https://elsewhere.example/api/pilot/v1/chat/completions", "origin is invalid"),
        (BINDING_URL + "/api/pilot/v1/admin/model-calls", "path is not allowed"),
        (BINDING_URL + "/api/pilot/v1/chat/completions?x=1", "target is invalid"),
    ):
        with pytest.raises(httpx.RequestError) as error:
            await transport.handle_async_request(httpx.Request("POST", url, content=b"{}"))
        assert fragment in str(error.value)
