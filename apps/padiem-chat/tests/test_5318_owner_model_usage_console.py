"""#5318 owner console read of the B14 call ledger.

The handlers are called the way the router calls them, on an app state that
carries the same authorizer, history store and signed B14 service transport the
worker sets. The fake transport records the exact path it was asked for, which is
where the interesting claims live: that a filter the console never heard of
cannot widen a query, that a page walks rather than truncates, that an
unconfigured ledger is never shown as "no model ran", and that nothing about the
service proof crosses the JSON boundary.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qsl, quote

import pytest

from starlette.datastructures import State
from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.platform_model_usage_routes import (
    LEDGER_AGGREGATE_PATH, LEDGER_LIST_PATH, model_usage_aggregate,
    model_usage_call_detail, model_usage_calls,
)

NO_AUTHORITY = None
OMITTED = object()

ADMIN = "usr_5318_model_usage_admin"
PLAIN = "usr_5318_signed_in_but_not_admin"
SECRET = "a-very-real-service-proof-secret-not-for-the-browser"
LOG_ID = "b14call_0123456789abcdef"

MEASURED = {
    "log_id": LOG_ID, "request_id": "b14req_1", "product": "chat",
    "origin_source": "caller_declared", "subject_ref": "usr_opaque_1",
    "tenant_ref": "ws_opaque_1", "membership_tier": "PRO",
    "requested_model_id": "google/gemini-3.1-flash-lite",
    "selected_model_id": "google/gemini-3.1-flash-lite",
    "selected_provider": "Google AI Studio",
    "actual_response_model": "gemini-3.1-flash-lite",
    "protocol": "native", "outcome": "success", "http_status": 200,
    "started_at": "2026-10-25T03:09:13Z", "elapsed_ms": 1851,
    "latency_source": "measured", "ttft_ms": 320, "streaming": 1,
    "attempt_count": 2, "fallback_used": 1, "fallback_depth": 1,
    "prompt_tokens": 2081, "completion_tokens": 414, "total_tokens": 2495,
    "reasoning_tokens": None, "token_source": "measured",
    "estimated_usd": 0.0042, "estimated_krw": 5.6,
    "cost_basis": "configured_snapshot", "currency": "USD",
}
# A second row shaped like the case that has no provider usage at all.
UNMEASURED = {**MEASURED, "log_id": "b14call_unmeasured_", "membership_tier": None,
              "token_source": "missing", "prompt_tokens": None, "completion_tokens": None,
              "total_tokens": None, "estimated_usd": None, "estimated_krw": None,
              "cost_basis": "unknown", "latency_source": "unknown", "elapsed_ms": None,
              "outcome": "error", "error_code": "upstream_timeout", "http_status": 504}


class Transport:
    """The signed B14 service-binding read, replaced by a recorder."""

    def __init__(self, *, status=200, payload=None, failure=None):
        self.paths = []
        self.status = status
        self.payload = payload if payload is not None else {"calls": [MEASURED, UNMEASURED], "total": 2}
        self.failure = failure

    async def get_json(self, path):
        self.paths.append(path)
        if self.failure is not None:
            raise self.failure
        return self.status, json.dumps(self.payload).encode()


class Authority:
    def __init__(self, *, is_admin=True, fails=False, missing=False):
        self.is_admin, self.fails = is_admin, fails
        if missing:
            self.is_missing = True

    async def is_global_model_admin(self, *, user_id):
        assert user_id in (ADMIN, PLAIN)
        if self.fails:
            raise RuntimeError("authority store detail must not escape")
        return self.is_admin


def request_for(path, *, transport=None, authority=OMITTED, owner=ADMIN):
    settings = Settings(session_secret="b14-model-usage-tests", auth_mode="mock",
                        public_base_url="https://chat.example.test")
    state = State()
    state.settings = settings
    state.history_store = object()
    if authority is not OMITTED:
        state.central_model_admin_authorizer = authority
    state.b14_service_transport = transport
    app = _App(state)
    headers = [(b"cookie", (SESSION_COOKIE + "=" + create_session_token(settings, owner)).encode())]
    if owner is None:
        headers = []
    split = path.split("?", 1)
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "path": split[0],
        "raw_path": split[0].encode(), "query_string": (split[1] if len(split) > 1 else "").encode(),
        "headers": headers, "scheme": "https", "server": (b"chat.example.test", 443),
        "client": ("127.0.0.1", 1), "root_path": "", "app": app,
        "path_params": {"log_id": split[0].rsplit("/", 1)[-1]},
    }
    return Request(scope)


class _App:
    def __init__(self, state):
        self.state = state


def call(handler, path, **kwargs):
    return asyncio.run(handler(request_for(path, **kwargs)))


def payload_of(response):
    return json.loads(response.body.decode())


# --------------------------------------------------------------------------
# authority
# --------------------------------------------------------------------------


def test_anonymous_and_non_admin_callers_are_refused_before_any_read():
    transport = Transport()
    anonymous = call(model_usage_calls, "/api/admin/model-usage/calls",
                     transport=transport, authority=Authority(), owner=None)
    assert anonymous.status_code == 401
    assert payload_of(anonymous)["error"]["code"] == "authentication_required"
    plain = call(model_usage_calls, "/api/admin/model-usage/calls",
                 transport=transport, authority=Authority(is_admin=False), owner=PLAIN)
    assert plain.status_code == 403
    assert payload_of(plain)["error"]["code"] == "global_model_admin_forbidden"
    # Neither caller caused a ledger read: the refusal is not a filtered view.
    assert transport.paths == []


def test_a_missing_or_broken_authorizer_refuses_rather_than_defaulting_open():
    missing = call(model_usage_calls, "/api/admin/model-usage/calls",
                   transport=Transport(), authority=NO_AUTHORITY, owner=ADMIN)
    assert missing.status_code == 503
    assert payload_of(missing)["error"]["code"] == "central_admin_not_configured"
    broken = call(model_usage_calls, "/api/admin/model-usage/calls",
                  transport=Transport(), authority=Authority(fails=True), owner=ADMIN)
    assert broken.status_code == 503
    assert payload_of(broken)["error"]["code"] == "central_admin_authority_unavailable"
    assert "detail" not in broken.body.decode()


# --------------------------------------------------------------------------
# query surface
# --------------------------------------------------------------------------


def test_filters_and_the_page_cursor_are_forwarded_bounded():
    transport = Transport()
    response = call(model_usage_calls,
                    "/api/admin/model-usage/calls?since=2026-10-01T00:00:00Z"
                    "&until=2026-10-20T00:00:00Z&selected_model_id=google%2Fgemini-3.1-flash-lite"
                    "&selected_provider=Google%20AI%20Studio&membership_tier=PRO&product=chat"
                    "&outcome=success&limit=25&offset=75",
                    transport=transport, authority=Authority(), owner=ADMIN)
    assert response.status_code == 200
    sent = transport.paths[0]
    assert sent.startswith(LEDGER_LIST_PATH + "?")
    query = dict(parse_qsl(sent.split("?", 1)[1]))
    assert query["since"] == "2026-10-01T00:00:00Z"
    assert query["selected_model_id"] == "google/gemini-3.1-flash-lite"
    assert query["membership_tier"] == "PRO"
    assert (query["limit"], query["offset"]) == ("25", "75")
    body = payload_of(response)
    assert body["ok"] is True and body["total"] == 2 and body["offset"] == 75
    assert body["requested"]["filters"]["product"] == "chat"


def test_a_filter_the_console_never_exposed_cannot_widen_the_query():
    transport = Transport()
    for attempt in ("?started_at=2020-01-01", "?prompt=hello", "?cost_basis=x&secret=1"):
        response = call(model_usage_calls, "/api/admin/model-usage/calls" + attempt,
                        transport=transport, authority=Authority(), owner=ADMIN)
        assert response.status_code == 422, attempt
        assert payload_of(response)["error"]["code"].startswith("unsupported_filter")
    assert transport.paths == []


def test_page_bounds_are_refused_instead_of_silently_read_as_a_different_page():
    transport = Transport()
    for attempt in ("limit=0", "limit=201", "offset=-1", "offset=100001", "limit=abc"):
        response = call(model_usage_calls, "/api/admin/model-usage/calls?" + attempt,
                        transport=transport, authority=Authority(), owner=ADMIN)
        assert response.status_code == 422, attempt
    assert transport.paths == []


def test_aggregate_only_accepts_the_ledger_grouping_vocabulary():
    transport = Transport(payload={"rows": [], "unit": "logical_request", "storage_state": "bound"})
    refused = call(model_usage_aggregate,
                   "/api/admin/model-usage/aggregate?group_by=subject_ref",
                   transport=transport, authority=Authority(), owner=ADMIN)
    assert refused.status_code == 422
    assert payload_of(refused)["error"]["code"] == "unsupported_group_by"
    trend = call(model_usage_aggregate,
                 "/api/admin/model-usage/aggregate?group_by=day&since=2026-10-01T00:00:00Z",
                 transport=transport, authority=Authority(), owner=ADMIN)
    assert trend.status_code == 200
    assert "group_by=day" in transport.paths[-1]
    assert "since=2026-10-01T00%3A00%3A00Z" in transport.paths[-1]


# --------------------------------------------------------------------------
# honesty of the projection
# --------------------------------------------------------------------------


def test_absent_usage_and_price_stay_absent_rather_than_becoming_zero():
    transport = Transport()
    body = payload_of(call(model_usage_calls, "/api/admin/model-usage/calls",
                           transport=transport, authority=Authority(), owner=ADMIN))
    measured, unmeasured = body["calls"]
    assert measured["usage_state"] == "measured" and measured["cost_state"] == "catalog_estimate"
    assert unmeasured["usage_state"] == "missing" and unmeasured["cost_state"] == "unknown"
    # The stored NULLs are carried through untouched; nothing is filled in.
    assert unmeasured["total_tokens"] is None and unmeasured["estimated_usd"] is None
    assert "0" not in json.dumps({key: unmeasured[key] for key in
                                  ("prompt_tokens", "completion_tokens", "total_tokens",
                                   "estimated_usd", "estimated_krw")})
    # A tier no caller declared is labelled, not counted as its own bucket.
    assert measured["membership_tier_declared"] is True
    assert unmeasured["membership_tier_declared"] is False
    assert unmeasured["identity_source"] == "caller_declared"


def test_an_unbound_ledger_is_reported_as_unconfigured_not_as_no_traffic():
    transport = Transport(status=503, payload={"error": {"code": "call_ledger_unavailable"},
                                               "storage_state": "not_configured"})
    response = call(model_usage_calls, "/api/admin/model-usage/calls",
                    transport=transport, authority=Authority(), owner=ADMIN)
    assert response.status_code == 503
    body = payload_of(response)
    assert body["storage_state"] == "not_configured"
    assert body["error"]["code"] == "call_ledger_unavailable"
    assert body["calls"] == []


def test_no_transport_and_a_failing_transport_never_leak_internals():
    absent = call(model_usage_calls, "/api/admin/model-usage/calls",
                  transport=None, authority=Authority(), owner=ADMIN)
    assert absent.status_code == 503
    assert payload_of(absent)["error"]["code"] == "model_usage_transport_unconfigured"

    transport = Transport(failure=RuntimeError("binding detail with a token"))
    broken = call(model_usage_calls, "/api/admin/model-usage/calls",
                  transport=transport, authority=Authority(), owner=ADMIN)
    assert broken.status_code == 502
    assert payload_of(broken)["error"]["code"] == "model_usage_read_failed"
    assert "token" not in broken.body.decode()


def test_the_screen_never_carries_the_proof_or_a_new_authority():
    from pathlib import Path

    from app.platform_model_usage_routes import (
        MODEL_USAGE_NEW_AUTHORITY, MODEL_USAGE_WRITES,
    )

    assert MODEL_USAGE_NEW_AUTHORITY is False
    assert MODEL_USAGE_WRITES is False
    # The proof is the transport's job. This module must not read the secret
    # binding at all, which is what keeps it off the JSON boundary.
    source = (Path(__file__).resolve().parents[1] / "app" / "platform_model_usage_routes.py"
              ).read_text(encoding="utf-8")
    for forbidden in ("PADIEM_B14_SERVICE_PROOF_SECRET", "proof_secret", "service_proof",
                      "SECRET", "cookie", "authorization"):
        assert forbidden not in source, forbidden
    response = call(model_usage_calls, "/api/admin/model-usage/calls",
                    transport=Transport(), authority=Authority(), owner=ADMIN)
    body = response.body.decode()
    for forbidden in (SECRET, "proof", "x-padiem-b14", "cookie"):
        assert forbidden not in body.lower()
    assert response.headers["cache-control"].startswith("private, no-store")


# --------------------------------------------------------------------------
# detail
# --------------------------------------------------------------------------


def test_detail_projects_every_physical_attempt_including_the_skipped_one():
    attempts = [
        {**MEASURED, "attempt_index": 0, "outcome": "error", "error_code": "upstream_timeout",
         "dispatched": 1, "token_source": "missing", "prompt_tokens": None,
         "total_tokens": None, "estimated_usd": None, "cost_basis": "unknown",
         "latency_source": "unknown", "elapsed_ms": None},
        {**MEASURED, "attempt_index": 1, "outcome": "success", "error_code": None,
         "dispatched": 1},
        {**MEASURED, "attempt_index": 2, "outcome": "success", "dispatched": 0},
    ]
    transport = Transport(payload={"call": {**MEASURED, "attempts": attempts},
                                    "storage_state": "bound"})
    body = payload_of(call(model_usage_call_detail, "/api/admin/model-usage/calls/" + LOG_ID,
                           transport=transport, authority=Authority(), owner=ADMIN))
    shown = body["call"]["attempts"]
    assert [a["attempt_index"] for a in shown] == [0, 1, 2]
    # The failed first attempt is still there next to the success that replaced it.
    assert shown[0]["outcome"] == "error" and shown[0]["usage_state"] == "missing"
    assert shown[2]["dispatched"] is False
    assert transport.paths == [LEDGER_LIST_PATH + "/" + LOG_ID]


def test_detail_refuses_an_id_that_is_not_a_ledger_key():
    transport = Transport()
    for bad in ("not-a-log-id", "b14call_" + "x" * 70):
        response = call(model_usage_call_detail, "/api/admin/model-usage/calls/" + quote(bad),
                        transport=transport, authority=Authority(), owner=ADMIN)
        assert response.status_code == 422, bad
    assert transport.paths == []
    missing = Transport(status=404, payload={"error": {"code": "call_not_found"}})
    refused = call(model_usage_call_detail, "/api/admin/model-usage/calls/" + LOG_ID,
                   transport=missing, authority=Authority(), owner=ADMIN)
    assert refused.status_code == 404
    assert payload_of(refused)["error"]["code"] == "call_not_found"
    assert transport.paths == []


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------


def test_the_routes_and_the_hub_card_are_wired_to_the_existing_authority():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    factory = (root / "app" / "app_factory.py").read_text(encoding="utf-8")
    for path, handler in (
        ("/api/admin/model-usage/calls", "model_usage_calls"),
        ("/api/admin/model-usage/calls/{log_id}", "model_usage_call_detail"),
        ("/api/admin/model-usage/aggregate", "model_usage_aggregate"),
    ):
        assert f'Route("{path}", {handler}, methods=["GET"])' in factory
    capabilities = (root / "app" / "platform_admin_routes.py").read_text(encoding="utf-8")
    # The screen answers to the authority model management already uses. Minting a
    # second capability would need its own grant path and could drift from it.
    assert '"model_usage_admin"' not in capabilities
    hub = (root / "static" / "admin.js").read_text(encoding="utf-8")
    assert '"./admin/model-usage"' in hub
    usage_card = hub.split('key: "model-usage"', 1)[1].split("},", 1)[0]
    assert "caps.central_model_admin === true" in usage_card
    page = (root / "static" / "admin" / "model-usage.html").read_text(encoding="utf-8")
    screen = (root / "static" / "admin-model-usage.js").read_text(encoding="utf-8")
    # Same conventions as the rest of the console: no second login, no form,
    # no HTML string building, and the gate exists before any fetch.
    assert "admin-model-usage.js" in page and "gatePanel" in page
    for forbidden in ("<form", 'type="password"', "innerHTML"):
        assert forbidden not in page
        assert forbidden not in screen
    assert 'credentials: "same-origin"' in screen
    assert "/api/admin/session" in screen
    # Nothing in the console asks the browser for a service proof or a secret.
    for forbidden in ("proof", "secret", "HMAC"):
        assert forbidden not in screen.lower()


def test_the_worker_transport_widens_only_by_the_ledger_prefix():
    """Run the real transport class against a fake binding, no network.

    The console hands this class a path assembled from its own constants, so this
    prefix rule is the only thing between an owner screen and an arbitrary signed
    read of the B14 Worker. The model-authority reads are re-checked here because
    they must keep the exact unsigned shape they had before the ledger joined.
    """
    import ast
    from pathlib import Path

    worker_path = Path(__file__).resolve().parents[1] / "worker.py"
    tree = ast.parse(worker_path.read_text("utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef)
        and item.name == "CloudflareB14ServiceTransport"
    )
    captured = []

    class Request:
        def __init__(self, url, **kwargs):
            captured.append((url, kwargs))
            self.js_object = self

    class Response:
        status = 200

    class Binding:
        async def fetch(self, request):
            return Response()

    async def read_body(response, *, max_bytes):
        return b"{}"

    class TooLarge(Exception):
        pass

    class BadRead(Exception):
        pass

    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[
            ast.alias(name="annotations")], level=0),
        node,
    ], type_ignores=[])
    ns = {
        "Request": Request,
        "json": json,
        "MAX_B14_RESPONSE_BYTES": 1024 * 1024,
        "read_bounded_service_binding_body": read_body,
        "ServiceBindingResponseTooLarge": TooLarge,
        "ServiceBindingResponseError": BadRead,
        "service_proof_headers": lambda secret, body: {"x-padiem-b14-proof": "signed"},
    }
    exec(compile(ast.fix_missing_locations(module), str(worker_path), "exec"), ns)
    transport = ns["CloudflareB14ServiceTransport"](Binding(), "the-secret")

    detail = f"{LEDGER_LIST_PATH}/{LOG_ID}"
    accepted = (LEDGER_LIST_PATH, detail, LEDGER_AGGREGATE_PATH, "/api/pilot/models")

    async def scenario():
        for path in accepted:
            assert await transport.get_json(path) == (200, b"{}")
        for smuggled in (
            f"{LEDGER_LIST_PATH}/../model-registration",
            "/api/pilot/v1/admin",
            "https://attacker.invalid/api/pilot/v1/admin/model-calls",
            "/",
        ):
            with pytest.raises(ValueError):
                await transport.get_json(smuggled)
    asyncio.run(scenario())

    assert [url for url, _ in captured] == ["https://b14.internal" + p for p in accepted]
    for url, kwargs in captured[:3]:
        assert kwargs["headers"] == {"x-padiem-b14-proof": "signed"}, url
    assert captured[3][1] == {"method": "GET"}
