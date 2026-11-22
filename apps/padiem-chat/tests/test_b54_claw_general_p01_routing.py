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

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from _support.claw_general_routing import (
    GENERAL_ROUTE_PATH,
    SIGNED_IN_USER_ID,
    SESSION_COOKIE,
    create_session_token,
    _AuthStore,
    _client,
    _make_adapter,
    _make_outcome,
    _payload,
    _settings,
)
from _support.claw_routing_sources import (
    app_factory_source,
    app_js_source,
    claw_general_routes_source,
    streaming_module_source,
    transport_source,
)

CLAW_GENERAL_SOURCE = claw_general_routes_source()
APP_FACTORY_SOURCE = app_factory_source()
APP_JS_SOURCE = app_js_source()
TRANSPORT_SOURCE = transport_source()



CLAW_GENERAL_ROUTE_HELPERS = (
    "_claw_general_user_text",
    "_claw_general_intake",
    "_claw_general_session_custom",
    "_claw_general_route_preflight",
    "_claw_general_pc_branch",
    "_claw_general_pc_work_context",
    "_claw_general_quota_gate",
    "_claw_general_authority_context",
    "_claw_general_catalog_gate",
    "_claw_general_run_claim",
    "_claw_general_grounding",
    "_claw_general_staging",
    "_claw_general_context_bundle",
    "_claw_general_terminal",
)


def _claw_general_blocks(source: str) -> str:
    names = ("claw_general_execute", *CLAW_GENERAL_ROUTE_HELPERS)
    return "".join(_strip_docstring(_python_block(source, name)) for name in names)


def _python_block(source: str, name: str) -> str:
    marker = next(
        candidate for candidate in (f"async def {name}(", f"def {name}(")
        if candidate in source
    )
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
    block = _claw_general_blocks(CLAW_GENERAL_SOURCE)
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


def test_every_claw_general_helper_is_scanned() -> None:
    discovered = set(re.findall(
        r"^(?:async )?def (_claw_general_[a-z0-9_]+)\(",
        CLAW_GENERAL_SOURCE, re.M,
    ))
    # The synchronous SSE projection is not a request-path helper. Any other
    # new helper must be added explicitly to the forbidden-path scan above.
    assert discovered - {"_claw_general_sse"} == set(CLAW_GENERAL_ROUTE_HELPERS)
    for name in CLAW_GENERAL_ROUTE_HELPERS:
        block = _strip_docstring(_python_block(CLAW_GENERAL_SOURCE, name)).lower()
        assert "api_chat_stream" not in block, name
        assert "b14_client" not in block, name
        assert "/api/chat/stream" not in block, name
        assert "b66" not in block, name
        assert "manual-intake" not in block, name


def test_claw_general_route_is_registered() -> None:
    assert "claw_general_execute" in APP_FACTORY_SOURCE
    assert '"/api/claw/general"' in APP_FACTORY_SOURCE


def test_frontend_claw_branch_uses_claw_route_without_chat_stream_fallback() -> None:
    claw_fn = _js_function(TRANSPORT_SOURCE, "requestClawGeneral")
    assert '"/api/claw/general"' in claw_fn
    assert '"/api/chat/stream"' not in claw_fn
    assert 'fetch("/api/chat/stream"' not in claw_fn
    # #7297: chat-streaming-module.js sends Claw general turns through the shared
    # Chat direct streaming path with payload.product = "claw".
    stream_source = streaming_module_source()
    assert "deps.chatTransport.requestStreaming(payload, signal)" in stream_source
    assert 'payload.product = "claw"' in stream_source
    assert "route && route.clawGeneral" in stream_source


def test_b62_chat_general_path_unchanged() -> None:
    # Standalone Padiem Chat keeps the direct B62 stream.
    streaming_fn = _js_function(TRANSPORT_SOURCE, "requestStreaming")
    assert '"/api/chat/stream"' in streaming_fn
    assert '"/api/orchestration"' in TRANSPORT_SOURCE
    stream_source = streaming_module_source()
    # The Claw decision is state-scoped in app.js and only annotates the route.
    assert "clawGeneralRequest" in APP_JS_SOURCE
    assert "clawGeneral: true" in stream_source
    # The flag is derived from product state: the Claw shell with the explicit
    # manual form hidden (i.e. the generic composer).
    assert 'shell.dataset.state === "claw"' in APP_JS_SOURCE
    # The standalone transport call stays byte-for-byte (also pinned by
    # tests/test_browser_streaming_contract.py).
    assert "deps.chatTransport.requestStreaming(payload, signal)" in stream_source
    assert "deps.chatTransport.requestCompleted(payload, signal)" in stream_source


def test_b66_product_boundary_unchanged() -> None:
    block = _strip_docstring(_claw_general_blocks(CLAW_GENERAL_SOURCE)).lower()
    assert "b66" not in block
    assert "quote" not in block


# ── #3655: opt-in one-shot canary evidence headers ──────────────────────────


def _make_evidence_outcome():
    outcome = _make_outcome()
    outcome.p01_run_id = "orch_evidence_001"
    # #5484: B14 reports `platform:<provider>/<model>`; the header must carry it.
    outcome.selected_route_id = "platform:opencode-go/muse-spark-1.3-contributor"
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
    assert (
        with_marker.headers["x-padiem-selected-route-id"]
        == "platform:opencode-go/muse-spark-1.3-contributor"
    )
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
