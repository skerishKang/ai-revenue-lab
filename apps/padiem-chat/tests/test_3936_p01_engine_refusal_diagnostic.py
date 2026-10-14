"""#3936: bounded non-secret attribution for a refused B62 -> Engine P01 dispatch.

Reproduces the live Production refusal (Engine caller-registry app authorization)
through the REAL ``/start-p01`` route and the REAL private Engine client, and
proves that:

* the public answer stays the single generic ``409 web_xlsx_p01_pause_refused``;
* the one-shot D1 reservation is retained and never retried;
* exactly one bounded, non-secret attribution event is emitted instead of the
  refusal being flattened into an unattributable generic error;
* no identifier, hash, credential, token, byte or Engine message text can enter
  that event.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_p01_browser_start import install_owner_run
from test_3580_web_xlsx_p01_request import harness, prepare, projected_pause
from test_3580_web_xlsx_selection_routes import RealSQLiteD1
from test_3580_web_xlsx_sources import request, OWNER

from app import web_xlsx_p01_refusal as refusal
from app.claw_web_xlsx_p01_owner_decision import D1WebXlsxP01OwnerDecisionStore
from app.claw_web_xlsx_p01_request import TrustedWebXlsxP01Request
from app.web_xlsx_p01_engine_client import CloudflareWebXlsxP01EngineClient
from app.web_xlsx_p01_refusal import (
    BOUNDED_STAGES, ENGINE_REFUSAL_STAGES, STAGE_CONTRACT_MISMATCH,
    STAGE_DID_NOT_PAUSE, STAGE_DISPATCH_UNKNOWN, STAGE_PAUSE_COMMIT_FAILED,
    STAGE_PAUSE_ISSUED, build_dispatch_event, classify_engine_refusal,
    emit_dispatch_event, parse_engine_error_code,
)

START = "/api/claw/office/web-selections/{}/start-p01"
STATUS = "/api/claw/office/web-selections/{}/p01-status"
CREDENTIAL = "test-credential-not-a-real-secret"
CALLER = "b54-p01-overlay-20260914-a1"

# The EXACT live Production Engine refusal shape for a request whose app_id is
# absent from the caller-registry entry: Engine worker.py maps
# ServiceIdentityError("service_app_not_authorized") to this body and HTTP 403.
LIVE_APP_AUTHORITY_REFUSAL = (
    403, {"ok": False, "error": {"code": "service_app_not_authorized"}},
)


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = None
        self._body = body

    async def text(self):
        return json.dumps(self._body, ensure_ascii=False)


class EngineBinding:
    """Service-binding stand-in returning one fixed Engine reply or raising."""

    def __init__(self, status=202, body=None, fail=False):
        self.status = status
        self.body = body
        self.fail = fail
        self.calls = []

    async def fetch(self, js):
        self.calls.append(js)
        if self.fail:
            raise RuntimeError("private Engine unavailable")
        return FakeResponse(self.status, self.body)


class CountingStore:
    """Wrap the real request store to force one commit outcome."""

    def __init__(self, inner):
        self.inner = inner
        self.reserves = 0
        self.commits = 0

    async def preflight_start(self, **kwargs):
        return await self.inner.preflight_start(**kwargs)

    async def reserve(self, request):
        self.reserves += 1
        return await self.inner.reserve(request)

    async def commit_pause(self, **kwargs):
        self.commits += 1
        return False


def real_client(binding):
    """The production private Engine client over a test service binding."""
    return CloudflareWebXlsxP01EngineClient(
        binding,
        caller_id=CALLER,
        credential=CREDENTIAL,
        request_factory=lambda url, method, headers, body: SimpleNamespace(
            js_object={"url": url, "method": method, "headers": headers,
                       "body": body}),
    )


async def scenario(*, engine=None, fetch_factory=None, store_factory=None,
                   emit=True):
    """Real route + real D1/sqlite harness, with an optional client/store swap."""
    app, settings, meta, r2, db, history, _fake_engine = harness()
    db.executescript((
        Path(__file__).resolve().parents[1] / "migrations"
        / "031_claw_web_xlsx_p01_decision_receipts.sql"
    ).read_text(encoding="utf-8"))
    db.executescript((
        Path(__file__).resolve().parents[1] / "migrations"
        / "040_claw_web_xlsx_p01_decision_release.sql"
    ).read_text(encoding="utf-8"))
    app.state.web_xlsx_p01_owner_decision_store = D1WebXlsxP01OwnerDecisionStore(
        RealSQLiteD1(db)
    )
    install_owner_run(history)
    events: list[dict] = []
    if emit:
        app.state.web_xlsx_p01_refusal_emitter = events.append
    original, selection = await prepare(app, settings)
    if fetch_factory is not None:
        app.state.web_xlsx_p01_pause_client = real_client(
            SimpleNamespace(fetch=fetch_factory(selection))
        )
    elif engine is not None:
        app.state.web_xlsx_p01_pause_client = real_client(engine)
    if store_factory is not None:
        app.state.web_xlsx_p01_request_store = store_factory(
            app.state.web_xlsx_p01_request_store
        )
    return app, settings, db, events, original, selection


def real_pause_fetch(selection, *, mutate=None):
    """Answer with the REAL Engine pause projection bound to this request."""

    async def fetch(js):
        args = json.loads(js["body"])["arguments"]
        projection = projected_pause(TrustedWebXlsxP01Request(
            owner_id=args["owner_id"], workspace_id=args["workspace_id"],
            run_id=args["run_id"], selection_ref=args["selection_ref"],
            document_id=args["document_id"],
            source_sha256=args["source_sha256"], filename="quote.xlsx",
            selection_expires_at=selection["expires_at"],
        ))
        if mutate is not None:
            mutate(projection)
        return FakeResponse(202, projection)

    return fetch


async def start(app, settings, selection_ref, *, payload=None):
    return await request(
        app, settings, owner=OWNER, method="POST",
        path=START.format(selection_ref), payload={} if payload is None else payload,
    )


async def status(app, settings, selection_ref):
    return await request(app, settings, owner=OWNER,
                         path=STATUS.format(selection_ref))


@pytest.mark.asyncio
async def test_live_production_app_authority_refusal_is_attributed_not_masked():
    web = await scenario(engine=EngineBinding(*LIVE_APP_AUTHORITY_REFUSAL))
    app, settings, db, events, original, selection = web
    ref = selection["selection_ref"]

    refused = await start(app, settings, ref)
    assert refused.status_code == 409
    assert refused.json() == {
        "ok": False, "error": {"code": "web_xlsx_p01_pause_refused"},
    }
    assert len(events) == 1
    assert events[0]["stage"] == "engine_app_not_authorized"
    assert events[0]["engine_status"] == 403
    assert events[0]["engine_code"] == "service_app_not_authorized"
    assert events[0]["pause_projected"] is False
    assert events[0]["reservation"] == "retained"

    # The one-shot reservation is retained: unknown status, exactly one row.
    assert db.execute(
        "SELECT status FROM claw_web_xlsx_p01_requests"
    ).fetchone()["status"] == "dispatching"
    state = (await status(app, settings, ref)).json()
    assert state["status"] == "request_unknown"
    assert state["owner_request_enabled"] is False
    assert state["owner_decision_enabled"] is False
    assert state["workcopy_created"] is False
    replay = await start(app, settings, ref)
    assert replay.status_code == 409
    assert db.execute("SELECT COUNT(*) FROM claw_web_xlsx_p01_requests").fetchone()[0] == 1

    # No request material may enter the attributed event or the public answer.
    emitted = json.dumps(events, ensure_ascii=False)
    for secret in (
        OWNER, "owner:" + OWNER, ref, original["document_id"],
        original["source_sha256"], CREDENTIAL, CALLER, original["filename"],
    ):
        assert secret not in emitted
    assert "stage" not in refused.text
    db.close()


@pytest.mark.asyncio
async def test_engine_source_continuation_and_caller_refusals_are_distinguished():
    for status_code, code, expected in (
        (403, "tool_source_authority_denied", "engine_source_authority_denied"),
        (503, "tool_source_authority_unavailable",
         "engine_source_authority_unavailable"),
        (503, "approval_verification_unavailable",
         "engine_approval_verification_unavailable"),
        (503, "continuation_store_unavailable",
         "engine_continuation_store_unavailable"),
        (503, "tool_runtime_unavailable", "engine_tool_runtime_unavailable"),
        (401, "service_authentication_failed", "engine_caller_unauthenticated"),
        (503, "service_identity_unavailable", "engine_identity_unavailable"),
    ):
        web = await scenario(engine=EngineBinding(
            status_code, {"ok": False, "error": {"code": code}},
        ))
        app, settings, db, events, _original, selection = web
        response = await start(app, settings, selection["selection_ref"])
        assert response.status_code == 409, (code, response.text)
        assert [event["stage"] for event in events] == [expected], code
        assert events[0]["engine_status"] == status_code
        assert events[0]["engine_code"] == code
        db.close()


@pytest.mark.asyncio
async def test_engine_replies_that_never_pause_are_attributed_separately():
    web = await scenario(engine=EngineBinding(
        202, {"ok": True, "orchestration": {"status": "paused"}},
    ))
    app, settings, db, events, _original, selection = web
    assert (await start(app, settings, selection["selection_ref"])).status_code == 409
    assert [event["stage"] for event in events] == [STAGE_DID_NOT_PAUSE]
    db.close()

    def break_tool(projection):
        projection["tool"]["canonical_tool_id"] = "tool:padiem:other@1"

    web = await scenario(
        fetch_factory=lambda selection: real_pause_fetch(selection, mutate=break_tool)
    )
    app, settings, db, events, _original, selection = web
    assert (await start(app, settings, selection["selection_ref"])).status_code == 409
    assert [event["stage"] for event in events] == [STAGE_CONTRACT_MISMATCH]
    assert events[0]["pause_projected"] is False
    db.close()


@pytest.mark.asyncio
async def test_unpersistable_engine_pause_is_attributed_as_commit_failure():
    web = await scenario(fetch_factory=real_pause_fetch, store_factory=CountingStore)
    app, settings, db, events, _original, selection = web
    store = app.state.web_xlsx_p01_request_store
    assert (await start(app, settings, selection["selection_ref"])).status_code == 409
    assert store.reserves == 1 and store.commits == 1
    assert [event["stage"] for event in events] == [STAGE_PAUSE_COMMIT_FAILED]
    assert events[0]["reservation"] == "retained"
    assert db.execute(
        "SELECT status FROM claw_web_xlsx_p01_requests"
    ).fetchone()["status"] == "dispatching"
    db.close()


@pytest.mark.asyncio
async def test_uncertain_transport_result_stays_the_existing_503_and_is_attributed():
    web = await scenario(engine=EngineBinding(fail=True))
    app, settings, db, events, _original, selection = web
    transport = await start(app, settings, selection["selection_ref"])
    assert transport.status_code == 503
    assert transport.json()["error"]["code"] == "web_xlsx_p01_dispatch_unknown"
    assert [event["stage"] for event in events] == [STAGE_DISPATCH_UNKNOWN]
    assert events[0]["engine_status"] is None
    assert db.execute("SELECT COUNT(*) FROM claw_web_xlsx_p01_requests").fetchone()[0] == 1
    db.close()


@pytest.mark.asyncio
async def test_verified_engine_pause_emits_the_positive_stage_and_waiting_state():
    web = await scenario(fetch_factory=real_pause_fetch)
    app, settings, db, events, _original, selection = web
    started = await start(app, settings, selection["selection_ref"])
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "waiting_p01"
    assert [event["stage"] for event in events] == [STAGE_PAUSE_ISSUED]
    assert events[0]["pause_projected"] is True
    assert (await status(app, settings, selection["selection_ref"])).json()[
        "status"] == "waiting_p01"
    # A positive stage event never carries Engine status/code material either.
    assert events[0]["engine_status"] is None and events[0]["engine_code"] is None
    db.close()


@pytest.mark.asyncio
async def test_emitter_failure_never_changes_the_public_answer():
    web = await scenario(engine=EngineBinding(*LIVE_APP_AUTHORITY_REFUSAL), emit=False)
    app, settings, db, _events, _original, selection = web

    def exploding_emitter(_event):
        raise RuntimeError("log pipeline unavailable")

    app.state.web_xlsx_p01_refusal_emitter = exploding_emitter
    response = await start(app, settings, selection["selection_ref"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "web_xlsx_p01_pause_refused"
    db.close()


def test_classifier_is_closed_and_never_repeats_engine_text():
    assert classify_engine_refusal(
        403, {"ok": False, "error": {"code": "service_app_not_authorized"}},
    ) == "engine_app_not_authorized"
    # Well-formed but unknown Engine code: bounded by the status class only.
    assert classify_engine_refusal(
        503, {"ok": False, "error": {"code": "brand_new_engine_code"}},
    ) == "engine_status_server_error"
    assert classify_engine_refusal(
        418, {"ok": False, "error": {"code": "brand_new_engine_code"}},
    ) == "engine_status_client_error"
    assert classify_engine_refusal("403", None) == "engine_response_unreadable"
    for hostile in (
        "Service_App_Not_Authorized", "service_app_not_authorized\nINJECTED",
        "x" * 300, "service-app-not-authorized", "", None, 17,
        ["service_app_not_authorized"], {"code": "service_app_not_authorized"},
    ):
        assert parse_engine_error_code({"error": {"code": hostile}}) in (
            "engine_code_absent", "engine_code_unrecognized",
        ), hostile
    assert parse_engine_error_code("not a mapping") == "engine_code_absent"
    # A hostile code can never appear in an event, whatever the status was.
    event = build_dispatch_event(
        stage=classify_engine_refusal(
            403, {"ok": False, "error": {"code": "service_app_not_authorized\nX"}},
        ),
        engine_status=403,
        engine_code=parse_engine_error_code(
            {"error": {"code": "service_app_not_authorized\nX"}}),
    )
    assert "INJECTED" not in json.dumps(event)
    assert event["engine_code"] == "engine_code_unrecognized"
    assert event["stage"] == "engine_status_client_error"


def test_event_shape_is_closed_and_unbounded_values_collapse():
    assert set(build_dispatch_event(stage="engine_refused")) == {
        "event", "service", "ts", "stage", "engine_status", "engine_code",
        "pause_projected", "reservation",
    }
    assert build_dispatch_event(stage="free_form_stage")["stage"] == (
        STAGE_DISPATCH_UNKNOWN
    )
    assert build_dispatch_event(
        stage="engine_refused", engine_status=9999,
        engine_code="Authorization: Bearer x",
    )["engine_status"] is None
    assert build_dispatch_event(
        stage="engine_refused", engine_status="403", engine_code={"a": 1},
    )["engine_code"] is None
    assert build_dispatch_event(
        stage="engine_refused", engine_status=True,
    )["engine_status"] is None
    assert build_dispatch_event(
        stage="engine_refused", reservation="something_else",
    )["reservation"] == "none"


def test_every_mapped_engine_stage_is_bounded():
    for stage in refusal._ENGINE_CODE_STAGES.values():
        assert stage in ENGINE_REFUSAL_STAGES, stage
    assert ENGINE_REFUSAL_STAGES <= BOUNDED_STAGES


def test_emitter_shape_and_default_logging_never_raise():
    captured = []

    def emitter(event):
        captured.append(event)

    emit_dispatch_event(stage=STAGE_DISPATCH_UNKNOWN, emitter=emitter)
    assert captured == [build_dispatch_event(stage=STAGE_DISPATCH_UNKNOWN)]

    def broken(_event):
        raise ValueError("no log sink")

    emit_dispatch_event(stage=STAGE_DISPATCH_UNKNOWN, emitter=broken)
    # No emitter configured: the module's own bounded JSON log path is used and
    # never raises into the request path.
    emit_dispatch_event(stage=STAGE_PAUSE_ISSUED, pause_projected=True)
