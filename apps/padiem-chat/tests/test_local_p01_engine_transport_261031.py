"""The CPython host's P01 Engine transport and its cron gate (#6356 follow-up).

Load-bearing claims: the transport reaches only a loopback origin over the same
closed path allowlist and byte envelope the Worker transport enforces, and the
host's cron tick reports the connected gate instead of a missing one. A real
socket round trip and a real ``PadiemAiEngineClient`` are used for the happy
path; a MockTransport is used only to observe refusals.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from kagent.p01_adapter import P01_APP_ID
from padiem_ai_engine_client import (
    ENGINE_DOCUMENT_ADMISSION_PATH,
    ENGINE_HEALTH_PATH,
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
    ENGINE_ORCHESTRATE_PATH,
    ENGINE_RESEARCH_PATH,
    PadiemAiEngineClient,
)

from app import worker_orchestration
from app.claw_p01_composition import compose_p01_lanes
from app.local_cron import run_once
from app.local_engine_transport import (
    ALLOWED_PATHS,
    MAX_ATTACHMENT_REQUEST_BYTES,
    MAX_ENGINE_MODEL_REQUEST_BYTES,
    MAX_ENGINE_REQUEST_BYTES,
    MAX_ENGINE_RESPONSE_BYTES,
    MODEL_REQUEST_PATHS,
    LocalEngineHttpTransport,
    LocalEngineTransportError,
    local_engine_origin,
)
from app.local_p01_engine import (
    LOCAL_P01_CALLER_ID_ENV,
    LOCAL_P01_CREDENTIAL_ENV,
    LOCAL_P01_ORIGIN_ENV,
    build_local_p01_lanes,
    local_p01_engine_config_from_env,
)
from app.worker_config import (
    P01_DIAG_CALLER_ID_SHAPE_INVALID,
    P01_DIAG_CLIENT_CONSTRUCTOR_ERROR,
    P01_DIAG_CREDENTIAL_LENGTH_INVALID,
    validate_p01_caller_and_credential,
)

LOOPBACK = "http://127.0.0.1:18731"
CREDENTIAL = "local-host-engine-credential-0123456789"


def _transport(handler, *, origin: str = LOOPBACK, **kwargs) -> LocalEngineHttpTransport:
    return LocalEngineHttpTransport(
        origin,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def _env(**overrides) -> dict[str, str]:
    base = {
        "PADIEM_CHAT_CPYTHON_HOST": "1",
        "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": "true",
        "PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN": "https://identity.example",
        "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET": "local-service-secret-0123456789abcdef",
    }
    base.update(overrides)
    return base


def _engine_env(**overrides) -> dict[str, str]:
    base = _env()
    base.update(
        {
            LOCAL_P01_ORIGIN_ENV: LOOPBACK,
            LOCAL_P01_CALLER_ID_ENV: "b62-chat-host",
            LOCAL_P01_CREDENTIAL_ENV: CREDENTIAL,
        }
    )
    base.update(overrides)
    return base


class _HealthStub(BaseHTTPRequestHandler):
    seen: list[dict[str, object]] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        _HealthStub.seen.append({"path": self.path})
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        del args


@pytest.fixture
def engine_stub():
    _HealthStub.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_host_transport_matches_the_worker_envelope_exactly():
    """If either side widens first, this parity test fails instead of drifting."""

    assert ALLOWED_PATHS == worker_orchestration._ALLOWED_ENGINE_PATHS
    assert MODEL_REQUEST_PATHS == worker_orchestration._ENGINE_MODEL_PATHS
    assert MAX_ENGINE_REQUEST_BYTES == worker_orchestration._MAX_ENGINE_REQUEST_BYTES
    assert MAX_ENGINE_MODEL_REQUEST_BYTES == (
        worker_orchestration._MAX_ENGINE_MODEL_REQUEST_BYTES
    )
    assert MAX_ENGINE_RESPONSE_BYTES == worker_orchestration._MAX_ENGINE_RESPONSE_BYTES
    assert MAX_ATTACHMENT_REQUEST_BYTES == (
        worker_orchestration._MAX_ATTACHMENT_REQUEST_BYTES
    )


def test_the_shared_caller_validation_is_one_authority():
    assert validate_p01_caller_and_credential("b62-chat-host", CREDENTIAL) is None
    assert (
        validate_p01_caller_and_credential("../escape", CREDENTIAL)
        == P01_DIAG_CALLER_ID_SHAPE_INVALID
    )
    assert (
        validate_p01_caller_and_credential("b62-chat-host", "short")
        == P01_DIAG_CREDENTIAL_LENGTH_INVALID
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://127.0.0.1:18731",
        "http://10.0.0.5:18731",
        "http://engine.internal:18731",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1:18731/engine",
        "http://127.0.0.1:18731?x=1",
        "http://user:pass@127.0.0.1:18731",
        "http://127.0.0.1:notaport",
        "  ",
    ],
)
def test_only_a_bare_loopback_http_origin_is_accepted(value):
    with pytest.raises(LocalEngineTransportError):
        local_engine_origin(value)


def test_loopback_origins_normalize_to_one_shape():
    assert local_engine_origin(" http://127.0.0.1:18731/ ") == LOOPBACK
    assert local_engine_origin("http://localhost:8811") == "http://localhost:8811"


async def test_the_origin_is_the_only_thing_rewritten():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["caller"] = request.headers.get("x-padiem-engine-caller")
        seen["credential"] = request.headers.get("x-padiem-engine-credential")
        seen["body"] = request.content
        return httpx.Response(200, json={"status": "ok"})

    transport = _transport(handler)
    response = await transport.request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}",
        headers={
            "X-Padiem-Engine-Caller": "b62-chat-host",
            "X-Padiem-Engine-Credential": CREDENTIAL,
        },
        body=b'{"goal":"tick"}',
    )

    assert response.status == 200
    assert seen["url"] == LOOPBACK + ENGINE_ORCHESTRATE_PATH
    assert seen["method"] == "POST"
    assert seen["caller"] == "b62-chat-host"
    assert seen["credential"] == CREDENTIAL
    assert seen["body"] == b'{"goal":"tick"}'


@pytest.mark.parametrize(
    "method,url",
    [
        ("GET", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}"),
        ("POST", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_HEALTH_PATH}"),
        ("POST", f"{ENGINE_INTERNAL_ORIGIN}/internal/v1/tools/execute"),
        ("POST", "https://someone-else.internal/internal/v1/orchestrate"),
        ("POST", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}?next=1"),
        ("DELETE", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}"),
    ],
)
async def test_unsupported_targets_are_refused_before_any_socket(method, url):
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    with pytest.raises(LocalEngineTransportError):
        await _transport(handler).request(
            method=method, url=url, headers={}, body=b"{}"
        )
    assert called is False


async def test_request_bodies_follow_the_worker_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = _transport(handler)
    await transport.request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}",
        headers={},
        body=b"x" * MAX_ENGINE_MODEL_REQUEST_BYTES,
    )
    await transport.request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_RESEARCH_PATH}",
        headers={},
        body=b"x" * MAX_ENGINE_REQUEST_BYTES,
    )
    with pytest.raises(LocalEngineTransportError):
        await transport.request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_RESEARCH_PATH}",
            headers={},
            body=b"x" * (MAX_ENGINE_REQUEST_BYTES + 1),
        )
    with pytest.raises(LocalEngineTransportError):
        await transport.request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}",
            headers={},
            body=b"x" * (MAX_ENGINE_MODEL_REQUEST_BYTES + 1),
        )


async def test_attachment_requests_keep_their_own_bound():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    await _transport(handler).request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_MULTIMODAL_ATTACHMENTS_PATH}",
        headers={},
        body=b"x" * MAX_ATTACHMENT_REQUEST_BYTES,
    )


async def test_document_admission_travels_on_the_text_bound():
    assert ENGINE_DOCUMENT_ADMISSION_PATH in ALLOWED_PATHS

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    await _transport(handler).request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_DOCUMENT_ADMISSION_PATH}",
        headers={},
        body=b"{}",
    )


async def test_a_response_past_the_bound_is_refused_not_buffered():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 128)

    with pytest.raises(LocalEngineTransportError):
        await _transport(handler, max_response_bytes=64).request(
            method="GET",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_HEALTH_PATH}",
            headers={},
            body=None,
        )


async def test_redirects_are_reported_to_the_caller_not_followed():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            302, headers={"location": f"{LOOPBACK}/elsewhere"}
        )

    response = await _transport(handler).request(
        method="GET",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_HEALTH_PATH}",
        headers={},
        body=None,
    )
    assert response.status == 302
    assert calls == [LOOPBACK + ENGINE_HEALTH_PATH]


async def test_a_caller_supplied_client_may_not_follow_redirects():
    with pytest.raises(LocalEngineTransportError):
        LocalEngineHttpTransport(
            LOOPBACK,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200)),
                follow_redirects=True,
            ),
        )


async def test_streaming_is_refused_instead_of_buffered():
    with pytest.raises(LocalEngineTransportError):
        await _transport(lambda request: httpx.Response(200)).stream_request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}",
            headers={},
            body=b"{}",
        )


async def test_a_real_engine_client_reaches_a_real_health_endpoint(engine_stub):
    transport = LocalEngineHttpTransport(engine_stub)
    client = PadiemAiEngineClient(
        transport=transport,
        app_id=P01_APP_ID,
        caller_id="b62-chat-host",
        credential=CREDENTIAL,
    )

    payload = await client.health()

    assert payload == {"status": "ok"}
    assert _HealthStub.seen == [{"path": ENGINE_HEALTH_PATH}]


def test_the_engine_surface_is_off_until_all_three_values_exist():
    assert local_p01_engine_config_from_env({}) == (None, None)
    assert local_p01_engine_config_from_env(
        {LOCAL_P01_ORIGIN_ENV: LOOPBACK}
    ) == (None, P01_DIAG_CALLER_ID_SHAPE_INVALID)


@pytest.mark.parametrize(
    "env,diagnostic",
    [
        (
            {
                LOCAL_P01_ORIGIN_ENV: "http://10.0.0.5:18731",
                LOCAL_P01_CALLER_ID_ENV: "b62-chat-host",
                LOCAL_P01_CREDENTIAL_ENV: CREDENTIAL,
            },
            "p01_engine_origin_invalid",
        ),
        (
            {
                LOCAL_P01_ORIGIN_ENV: LOOPBACK,
                LOCAL_P01_CALLER_ID_ENV: "not a caller",
                LOCAL_P01_CREDENTIAL_ENV: CREDENTIAL,
            },
            P01_DIAG_CALLER_ID_SHAPE_INVALID,
        ),
        (
            {
                LOCAL_P01_ORIGIN_ENV: LOOPBACK,
                LOCAL_P01_CALLER_ID_ENV: "b62-chat-host",
                LOCAL_P01_CREDENTIAL_ENV: "too-short",
            },
            P01_DIAG_CREDENTIAL_LENGTH_INVALID,
        ),
    ],
)
def test_a_malformed_surface_fails_closed_with_a_bounded_diagnostic(env, diagnostic):
    config, actual = local_p01_engine_config_from_env(env)
    assert config is None
    assert actual == diagnostic


def test_a_valid_surface_normalizes_the_origin():
    config, diagnostic = local_p01_engine_config_from_env(
        {
            LOCAL_P01_ORIGIN_ENV: "http://127.0.0.1:18731/",
            LOCAL_P01_CALLER_ID_ENV: "b62-chat-host",
            LOCAL_P01_CREDENTIAL_ENV: CREDENTIAL,
        }
    )
    assert diagnostic is None
    assert config is not None
    assert config.origin == LOOPBACK


def test_both_p01_lanes_compose_over_the_loopback_transport(engine_stub):
    adapter, continuation, diagnostic = build_local_p01_lanes(
        _engine_env(**{LOCAL_P01_ORIGIN_ENV: engine_stub})
    )
    assert diagnostic is None
    assert adapter is not None
    assert continuation is not None


async def test_the_host_composes_exactly_the_worker_lane_wiring():
    """The host must not become a second Engine protocol with its own lanes."""

    engine_client = PadiemAiEngineClient(
        transport=_transport(lambda request: httpx.Response(200, json={})),
        app_id=P01_APP_ID,
        caller_id="b62-chat-host",
        credential=CREDENTIAL,
    )
    adapter, continuation = compose_p01_lanes(
        engine_client, allow_subject_identity=False
    )
    host_adapter, host_continuation, diagnostic = build_local_p01_lanes(_engine_env())

    assert diagnostic is None
    assert type(host_adapter) is type(adapter)
    assert type(host_continuation) is type(continuation)


def test_the_cron_tick_reaches_the_connected_engine_gate():
    assert run_once(_engine_env()).endswith(
        "P01_ENGINE_CONNECTED transport=loopback_http"
    )


def test_the_cron_tick_still_reports_the_unbound_lane_without_an_origin():
    assert run_once(_env()).endswith(
        "NOT_CONFIGURED reason=p01_engine_transport_unbound"
    )


def test_the_cron_tick_never_echoes_the_configured_origin():
    status = run_once(_engine_env(**{LOCAL_P01_ORIGIN_ENV: "http://10.0.0.5:18731"}))
    assert status.endswith("NOT_CONFIGURED reason=p01_engine_origin_invalid")
    assert "10.0.0.5" not in status
    assert "18731" not in status


def test_a_broken_composition_is_a_bounded_state(monkeypatch):
    from app import local_cron

    def explode(env):
        raise RuntimeError("boom with a secret inside")

    monkeypatch.setattr(local_cron, "build_local_p01_adapter", explode)
    status = run_once(_engine_env())
    assert status.endswith("NOT_CONFIGURED reason=composition_unavailable")
    assert "boom" not in status


def test_engine_client_constructor_failure_is_named():
    from types import SimpleNamespace

    from app import local_p01_engine

    # A redirect-following client is refused by the transport constructor
    # (ValueError), which the composition reports as one bounded constant.
    adapter, continuation, diagnostic = local_p01_engine.build_local_p01_lanes(
        _engine_env(), client=SimpleNamespace(follow_redirects=True)
    )
    assert adapter is None and continuation is None
    assert diagnostic == P01_DIAG_CLIENT_CONSTRUCTOR_ERROR
