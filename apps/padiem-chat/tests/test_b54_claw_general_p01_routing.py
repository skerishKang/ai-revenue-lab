"""#3539 — B54 Claw general composer runs on the canonical P01 Engine lane.

Proves the finish-first routing contract at source level and through the real
Starlette app:

- a generic Claw submit reaches the existing #3382 ``claw_p01_adapter`` lane;
- the canonical USER subject is revalidated BEFORE the P01/Engine dispatch;
- an unbound P01 lane fails closed (503) and never falls through to the
  standalone B62 direct-B14 ``/api/chat/stream`` route;
- the standalone B62 chat path and the B66 product boundary are unchanged.

No live Engine/provider call is made: the adapter is injected as a stub.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings

APP_DIR = Path(__file__).resolve().parents[1]
CLAW_GENERAL_SOURCE = (APP_DIR / "app" / "claw_general_routes.py").read_text(encoding="utf-8")
APP_FACTORY_SOURCE = (APP_DIR / "app" / "app_factory.py").read_text(encoding="utf-8")
APP_JS_SOURCE = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
TRANSPORT_SOURCE = (APP_DIR / "static" / "chat-transport.js").read_text(encoding="utf-8")

GENERAL_ROUTE_PATH = "/api/claw/general"
SIGNED_IN_USER_ID = "usr_" + "7" * 32


def _python_block(source: str, name: str) -> str:
    marker = f"async def {name}("
    start = source.index(marker)
    rest = source[start + len(marker):]
    candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
    end = start + len(marker) + (min(candidates) if candidates else len(rest))
    return source[start:end]


def _js_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    rest = source[start + len(marker):]
    candidates = [
        i
        for i in (
            rest.find("\n  async function "),
            rest.find("\n  function "),
            rest.find("\n  window.PadiemChatTransport"),
            rest.find("\n})();"),
        )
        if i != -1
    ]
    end = start + len(marker) + (min(candidates) if candidates else len(rest))
    return source[start:end]


def _strip_docstring(block: str) -> str:
    """Drop the leading triple-quoted docstring so prose is not read as code."""
    first = block.find('"""')
    if first == -1:
        return block
    second = block.find('"""', first + 3)
    if second == -1:
        return block
    return block[:first] + block[second + 3:]


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-general-client.apps.googleusercontent.com",
        "google_client_secret": "claw-general-google-secret",
        "session_secret": "claw-general-session-secret-not-a-real-credential",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


class _AuthStore:
    """Presence-only auth stub: no history/conversation authority is exercised."""

    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        return None


def _make_outcome(*, status: str = "completed", answer: str | None = "P01 결과"):
    status_mock = MagicMock()
    status_mock.value = status
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = "run_general"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_general"
    outcome.p01_event_count = 1
    return outcome


def _make_adapter(*, outcome=None, subject_lane: bool = False) -> MagicMock:
    adapter = MagicMock()
    adapter.subject_identity_lane = subject_lane
    adapter.execute = AsyncMock(return_value=outcome or _make_outcome())
    return adapter


@contextmanager
def _client(adapter=None):
    app = create_app(settings=_settings(), history_store=_AuthStore(), claw_p01_adapter=adapter)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


def _payload(**extra) -> dict:
    payload = {"messages": [{"role": "user", "content": "일반 요청입니다."}], "tier": "plus"}
    payload.update(extra)
    return payload


# ── routing: generic Claw submit uses the P01 adapter ────────────────────────


def test_claw_general_submit_uses_p01_adapter_once() -> None:
    adapter = _make_adapter()
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in resp.text
    assert "P01 결과" in resp.text
    assert "event: done" in resp.text
    # PROVIDER_CALL_MAX contract: exactly one Engine dispatch per submit.
    adapter.execute.assert_awaited_once()


def test_claw_general_dispatch_passes_server_resolved_subject_and_tier() -> None:
    adapter = _make_adapter()
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 200
    kwargs = adapter.execute.await_args.kwargs
    assert kwargs["product_tier"] is not None
    # Identity lane off (no bound Control Plane authority): historical contract.
    assert kwargs["subject_id"] is None


def test_claw_general_unbound_adapter_fails_closed_without_b14() -> None:
    with _client(None) as client:
        b14_spy = MagicMock()
        client.app.state.b14_client = b14_spy
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "engine_not_configured"
    # No direct-B14 fallback of any kind.
    assert b14_spy.stream_text_auto.call_count == 0
    assert b14_spy.complete.call_count == 0


def test_claw_general_revalidates_canonical_subject_before_dispatch() -> None:
    # Identity lane ON but no trusted Control Plane authority bound -> the
    # canonical B54 session cannot resolve, so the request fails closed BEFORE
    # the P01/Engine dispatch.
    adapter = _make_adapter(subject_lane=True)
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "canonical_b54_session_unavailable"
    adapter.execute.assert_not_called()


def test_claw_general_rejects_malformed_input_without_dispatch() -> None:
    adapter = _make_adapter()
    with _client(adapter) as client:
        empty = client.post(GENERAL_ROUTE_PATH, json={"messages": []})
        missing = client.post(GENERAL_ROUTE_PATH, json={})
        bad_role = client.post(
            GENERAL_ROUTE_PATH, json={"messages": [{"role": "system", "content": "x"}]}
        )
        bad_tier = client.post(GENERAL_ROUTE_PATH, json=_payload(tier="enterprise"))
    assert empty.status_code == 400
    assert missing.status_code == 400
    assert bad_role.status_code == 400
    assert bad_tier.status_code == 422
    adapter.execute.assert_not_called()


def test_claw_general_approval_required_is_refused_not_faked() -> None:
    adapter = _make_adapter(outcome=_make_outcome(status="waiting_approval", answer=None))
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "claw_general_approval_required"


def test_claw_general_incomplete_result_fails_closed() -> None:
    adapter = _make_adapter(outcome=_make_outcome(status="failed", answer=None))
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "engine_execution_failed"


# ── source contract: no direct-B14 fallback, boundaries intact ───────────────


def test_claw_general_source_has_no_chat_stream_or_b14_or_b66() -> None:
    block = _python_block(CLAW_GENERAL_SOURCE, "claw_general_execute")
    assert "claw_p01_adapter" in block
    assert "adapter.execute" in block
    assert "resolve_current_b54_canonical_session" in block
    assert "subject_id" in block
    code = _strip_docstring(block)
    lowered = code.lower()
    assert "api_chat_stream" not in lowered
    assert "b14_client" not in lowered
    assert "/api/chat/stream" not in lowered
    assert "b66" not in lowered
    # No manual-intake semantics are reused: the route is a distinct B54 product
    # boundary, not a thin wrapper over the manual intake flow. (The shared
    # MAX_MANUAL_INTAKE_BODY_BYTES bound is a request-size constant only.)
    assert "manual-intake" not in lowered
    assert "ManualIntakeRequest" not in code
    assert "ManualIntakeRouter" not in code
    assert "ManualIntakeAction" not in code
    assert "_ACTION_MAP" not in code


def test_claw_general_route_is_registered() -> None:
    assert "claw_general_execute" in APP_FACTORY_SOURCE
    assert '"/api/claw/general"' in APP_FACTORY_SOURCE


def test_frontend_claw_branch_uses_claw_route_without_chat_stream_fallback() -> None:
    claw_fn = _js_function(TRANSPORT_SOURCE, "requestClawGeneral")
    assert '"/api/claw/general"' in claw_fn
    # No B62 stream target of any kind is reachable from the claw lane.
    assert '"/api/chat/stream"' not in claw_fn
    assert 'fetch("/api/chat/stream"' not in claw_fn
    # app.js selects the claw lane from product state and returns it directly;
    # there is no fallthrough to the B62 stream for a Claw general request.
    assert "requestClawGeneral(payload, signal)" in APP_JS_SOURCE
    assert "route && route.clawGeneral" in APP_JS_SOURCE


def test_b62_chat_general_path_unchanged() -> None:
    # Standalone Padiem Chat keeps the direct B62 stream.
    streaming_fn = _js_function(TRANSPORT_SOURCE, "requestStreaming")
    assert '"/api/chat/stream"' in streaming_fn
    assert '"/api/orchestration"' in TRANSPORT_SOURCE
    # The Claw decision is state-scoped in app.js and only annotates the route.
    assert "clawGeneralRequest" in APP_JS_SOURCE
    assert "clawGeneral: true" in APP_JS_SOURCE
    # The flag is derived from product state: the Claw shell with the explicit
    # manual form hidden (i.e. the generic composer).
    assert 'shell.dataset.state === "claw"' in APP_JS_SOURCE
    # The standalone transport call stays byte-for-byte (also pinned by
    # tests/test_browser_streaming_contract.py).
    assert "chatTransport.requestStreaming(payload, signal)" in APP_JS_SOURCE
    assert "chatTransport.requestCompleted(payload, signal)" in APP_JS_SOURCE


def test_b66_product_boundary_unchanged() -> None:
    block = _strip_docstring(_python_block(CLAW_GENERAL_SOURCE, "claw_general_execute")).lower()
    assert "b66" not in block
    assert "quote" not in block


# ── #3655: opt-in one-shot canary evidence headers ──────────────────────────


def _make_evidence_outcome():
    outcome = _make_outcome()
    outcome.p01_run_id = "orch_evidence_001"
    outcome.selected_route_id = "plus.agnes-3.0-flash.v1"
    outcome.provider_attempt_count = 1
    outcome.fallback_used = False
    return outcome


def test_claw_general_evidence_headers_emitted_only_with_opt_in_marker() -> None:
    adapter = _make_adapter(outcome=_make_evidence_outcome())
    with _client(adapter) as client:
        with_marker = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )
        without_marker = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert with_marker.status_code == 200
    assert with_marker.headers["x-padiem-claw-run-id"].startswith("run_")
    assert with_marker.headers["x-padiem-orchestration-run-id"] == "orch_evidence_001"
    assert with_marker.headers["x-padiem-selected-route-id"] == "plus.agnes-3.0-flash.v1"
    assert with_marker.headers["x-padiem-provider-attempts"] == "1"
    assert with_marker.headers["x-padiem-fallback-used"] == "false"
    # Without the exact marker the normal user surface is byte-identical.
    assert without_marker.status_code == 200
    assert "x-padiem-claw-run-id" not in without_marker.headers
    assert "x-padiem-orchestration-run-id" not in without_marker.headers
    assert "x-padiem-selected-route-id" not in without_marker.headers
    assert "x-padiem-provider-attempts" not in without_marker.headers
    assert "x-padiem-fallback-used" not in without_marker.headers


def test_claw_general_evidence_headers_drop_malformed_values() -> None:
    outcome = _make_evidence_outcome()
    outcome.p01_run_id = "bad id with spaces"
    outcome.selected_route_id = "not a route id!"
    outcome.provider_attempt_count = 99
    outcome.fallback_used = True
    adapter = _make_adapter(outcome=outcome)
    with _client(adapter) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )
    assert resp.status_code == 200
    # A value that fails its grammar is omitted, never degraded.
    assert "x-padiem-orchestration-run-id" not in resp.headers
    assert "x-padiem-selected-route-id" not in resp.headers
    assert resp.headers["x-padiem-provider-attempts"] == "99"
    assert resp.headers["x-padiem-fallback-used"] == "true"


def test_claw_general_error_response_carries_bounded_detail_and_run_ref() -> None:
    from kagent.p01_adapter import (
        P01_FAILURE_DETAIL_PROVIDER_SERVER_ERROR,
        P01AdapterError,
        P01DispatchClass,
    )

    adapter = _make_adapter()
    adapter.execute = AsyncMock(
        side_effect=P01AdapterError(
            "p01_engine_request_failed",
            "P01 orchestration failed at the Engine boundary.",
            dispatch_class=P01DispatchClass.UNKNOWN,
            failure_detail=P01_FAILURE_DETAIL_PROVIDER_SERVER_ERROR,
        )
    )
    with _client(adapter) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["detail"] == "engine_provider_server_error"
    # The outcome never materialized on this path: only the route-minted run
    # id is available as the correlation ref.
    assert resp.headers["x-padiem-claw-run-id"].startswith("run_")
    assert "x-padiem-orchestration-run-id" not in resp.headers
