"""#5484: the Engine admission lane receives the canonical subject, not the owner key.

The Engine asks the Control Plane for an engine entitlement by **canonical
subject**. The B62 product-local owner key (``usr_*``) is not a canonical
subject id, so the Control Plane reverse product-user lookup finds no product
identity link and fails closed. The Engine then answers 503
``entitlement_unavailable`` and the Chat ``POST /api/orchestration`` surfaces
the same 503, which fails the whole Chat turn.

The canonical-subject bridge (#1617) and its resolver already exist in this
repository. Only the Production composition in ``worker.py`` was missing the
resolver, so every Engine request carried the product-local owner key.

These tests pin three things:

1. the Production composition passes a canonical subject resolver;
2. the composed bridge is the canonical-subject bridge, and an unbound
   composition stays exactly as it was;
3. the Engine request carries the canonical subject while the product history
   and audit rows keep the product-local owner key.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.canonical_orchestration_bridge import CanonicalSubjectB62EngineOrchestrationBridge
from app.orchestration_bridge import B62EngineOrchestrationBridge, OrchestrationSnapshot
from app.task_modes import get_task_mode
from app.worker_config import P01_ENGINE_SERVICE_BINDING_NAME
from app.worker_orchestration import (
    ORCHESTRATION_ENABLED_ENV,
    build_orchestration_bridge,
)

PRODUCT_USER = "usr_0123456789abcdef0123456789abcdef"
CANONICAL_SUBJECT = "subject:padiem:user:canonical-5484"
VALID_CALLER = "b54-p01-overlay-20260914-a1"
VALID_CREDENTIAL = "c" * 48
LIVE = SimpleNamespace(runtime_mode="b14")

WORKER_SOURCE = Path(__file__).resolve().parents[1] / "worker.py"


def _env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        ORCHESTRATION_ENABLED_ENV: "true",
        P01_ENGINE_SERVICE_BINDING_NAME: SimpleNamespace(name="engine-service"),
        "P01_ENGINE_CALLER_ID": VALID_CALLER,
        "P01_ENGINE_CREDENTIAL": VALID_CREDENTIAL,
    }
    values.update(overrides)
    return values


def _request_factory(url: str, **kwargs: object) -> object:  # pragma: no cover
    raise AssertionError("composition must not perform network transport")


class _Resolver:
    def __init__(self, subject: str = CANONICAL_SUBJECT) -> None:
        self.subject = subject
        self.calls: list[str] = []

    async def resolve_subject_id(self, *, product_user_id: str) -> str:
        self.calls.append(product_user_id)
        return self.subject


def test_production_composition_passes_the_canonical_subject_resolver() -> None:
    """The regression guard: the Worker must hand the bridge a resolver.

    Removing the wiring restores the 503 ``entitlement_unavailable`` failure
    for every Chat turn, so this assertion must fail when the defect returns.
    """

    source = WORKER_SOURCE.read_text(encoding="utf-8")

    assert "canonical_subject_resolver=canonical_subject_resolver" in source
    assert "RefreshingCanonicalSubjectResolver" in source


def test_the_production_composition_keeps_the_resolver_absent_when_unconfigured() -> None:
    """A deployment without the identity authority or shadow store stays unbound."""

    source = WORKER_SOURCE.read_text(encoding="utf-8")

    assert (
        "if identity_authority is not None and identity_shadow_store is not None"
        in source
    )


def test_bridge_composes_the_canonical_subject_bridge_with_a_resolver() -> None:
    bridge = build_orchestration_bridge(
        _env(),
        settings=LIVE,
        db_binding=object(),
        request_factory=_request_factory,
        canonical_subject_resolver=_Resolver(),
    )

    assert bridge is not None
    assert isinstance(bridge, CanonicalSubjectB62EngineOrchestrationBridge)
    assert bridge.ready is True


def test_bridge_stays_unbound_without_a_resolver() -> None:
    bridge = build_orchestration_bridge(
        _env(),
        settings=LIVE,
        db_binding=object(),
        request_factory=_request_factory,
    )

    assert bridge is not None
    assert not isinstance(bridge, CanonicalSubjectB62EngineOrchestrationBridge)
    assert isinstance(bridge, B62EngineOrchestrationBridge)


class _FakeClient:
    def __init__(self, *, paused: bool = False) -> None:
        self.orchestrate_request: dict | None = None
        self.paused = paused

    async def orchestrate(self, request):
        self.orchestrate_request = dict(request)
        if self.paused:
            return {
                "events": [
                    {
                        "event_id": "evt_1",
                        "run_id": "run_1",
                        "trace_id": "trace_1",
                        "app_id": "padiem-chat",
                        "kind": "run_started",
                        "sequence": 1,
                    },
                    {
                        "event_id": "evt_2",
                        "run_id": "run_1",
                        "trace_id": "trace_1",
                        "app_id": "padiem-chat",
                        "kind": "approval_paused",
                        "sequence": 2,
                    },
                ],
                "approval_pause": {
                    "status": "paused",
                    "continuation_id": "pause_1",
                    "requirement": "user_confirmation",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                },
                "continuation_ref": "cont_abcdefgh12345678",
            }
        return {
            "execution": {"answer": "OK"},
            "events": [
                {
                    "event_id": "evt_1",
                    "run_id": "run_1",
                    "trace_id": "trace_1",
                    "app_id": "padiem-chat",
                    "kind": "run_started",
                    "sequence": 1,
                },
                {
                    "event_id": "evt_2",
                    "run_id": "run_1",
                    "trace_id": "trace_1",
                    "app_id": "padiem-chat",
                    "kind": "run_completed",
                    "sequence": 2,
                },
            ],
            "approval_pause": None,
        }


class _FakeStore:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def save_pause(self, **kwargs):
        self.saved.append(kwargs)

    async def load_active(self, *, user_id, continuation_ref):
        raise AssertionError("no continuation is loaded in this test")

    async def record_decision(self, **kwargs):  # pragma: no cover
        raise AssertionError("no decision is recorded in this test")

    async def set_state(self, **kwargs):  # pragma: no cover
        raise AssertionError("no state transition happens in this test")


def _canonical_bridge(*, paused: bool = False):
    client = _FakeClient(paused=paused)
    store = _FakeStore()
    resolver = _Resolver()
    bridge = CanonicalSubjectB62EngineOrchestrationBridge(
        client=client,
        store=store,
        canonical_subject_resolver=resolver,
    )
    return bridge, client, store, resolver


@pytest.mark.asyncio
async def test_the_engine_request_carries_the_canonical_subject_not_the_owner_key() -> None:
    """The load-bearing contract: the Engine must not receive ``usr_*``.

    The Control Plane entitlement authority keys the engine entitlement by
    canonical subject, so a product-local owner key fails the reverse
    product-user lookup and the whole admission fails closed.
    """

    bridge, client, store, resolver = _canonical_bridge()

    result = await bridge.start(
        user_id=PRODUCT_USER,
        messages=({"role": "user", "content": "안녕"},),
        skill=get_task_mode("auto"),
        model_id="b14/model",
        user_text="안녕",
        conversation_id=None,
    )

    assert resolver.calls == [PRODUCT_USER]
    assert client.orchestrate_request is not None
    subject_id = client.orchestrate_request["subject_id"]
    assert subject_id == CANONICAL_SUBJECT
    assert subject_id != PRODUCT_USER
    assert not subject_id.startswith("usr_")
    assert result.answer == "OK"


@pytest.mark.asyncio
async def test_the_product_history_rows_keep_the_product_local_owner_key() -> None:
    """The canonical subject must not leak into B62 ownership rows."""

    bridge, _client, store, _resolver = _canonical_bridge(paused=True)

    await bridge.start(
        user_id=PRODUCT_USER,
        messages=({"role": "user", "content": "안녕"},),
        skill=get_task_mode("auto"),
        model_id="b14/model",
        user_text="안녕",
        conversation_id=None,
    )

    assert store.saved
    assert store.saved[0]["user_id"] == PRODUCT_USER
    assert store.saved[0]["engine_request"]["subject_id"] == CANONICAL_SUBJECT


@pytest.mark.asyncio
async def test_a_resolver_failure_fails_closed_without_calling_the_engine() -> None:
    """An unavailable canonical authority must never reach the Engine."""

    class _FailingResolver:
        async def resolve_subject_id(self, *, product_user_id: str) -> str:
            raise RuntimeError("identity authority unavailable")

    client = _FakeClient()
    bridge = CanonicalSubjectB62EngineOrchestrationBridge(
        client=client,
        store=_FakeStore(),
        canonical_subject_resolver=_FailingResolver(),
    )

    from app.orchestration_bridge import B62OrchestrationError

    with pytest.raises(B62OrchestrationError) as excinfo:
        await bridge.start(
            user_id=PRODUCT_USER,
            messages=({"role": "user", "content": "안녕"},),
            skill=get_task_mode("auto"),
            model_id="b14/model",
            user_text="안녕",
            conversation_id=None,
        )

    assert excinfo.value.status_code == 503
    assert client.orchestrate_request is None


def test_the_orchestration_snapshot_contract_is_unchanged() -> None:
    """The B62 owner key stays a product-local id in the snapshot contract."""

    snapshot = OrchestrationSnapshot(
        continuation_ref="cont_abcdefgh12345678",
        user_id=PRODUCT_USER,
        pause_id="pause_1",
        engine_request={"subject_id": CANONICAL_SUBJECT},
        user_text="안녕",
        conversation_id=None,
        expires_at="2099-01-01T00:00:00+00:00",
        state="active",
    )

    assert snapshot.user_id == PRODUCT_USER
    assert snapshot.engine_request["subject_id"] == CANONICAL_SUBJECT

# #5573 / #5765: exercise the production-selected subclass through the real SDK.
class _StreamTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.closed = False

    async def request(self, **kwargs):
        raise AssertionError("stream must not fall back to buffered orchestration")

    async def stream_request(self, *, method, url, headers, body):
        from padiem_ai_engine_client import EngineStreamTransportResponse

        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        event = {
            "event_id": "evt_1", "run_id": "run_1", "trace_id": "trace_1",
            "app_id": "padiem-chat", "kind": "run_started", "sequence": 1,
        }
        completed = {**event, "event_id": "evt_2", "kind": "run_completed", "sequence": 2}

        async def chunks():
            try:
                for kind, value in (
                    ("event", event),
                    ("event", completed),
                    ("orchestration", {
                        "events": [event, completed],
                        "execution": {"answer": "OK"},
                        "approval_pause": None,
                    }),
                ):
                    yield (json.dumps({"ok": True, kind: value}) + "\n").encode()
            finally:
                self.closed = True

        return EngineStreamTransportResponse(
            status=200, chunks=chunks(), headers={"content-type": "application/x-ndjson"},
        )


def _selected_stream_bridge(monkeypatch, *, with_resolver: bool):
    resolver = _Resolver() if with_resolver else None
    bridge = build_orchestration_bridge(
        _env(), settings=LIVE, db_binding=object(), request_factory=_request_factory,
        canonical_subject_resolver=resolver,
    )
    assert bridge is not None
    assert isinstance(bridge, CanonicalSubjectB62EngineOrchestrationBridge) is with_resolver
    transport = _StreamTransport()
    monkeypatch.setattr(bridge._client, "_transport", transport)
    return bridge, transport, resolver


_STREAM_SELECTIONS = [
    pytest.param(True, id="identity_authority_and_shadow_store_supply_resolver_selects_canonical"),
    pytest.param(False, id="no_canonical_subject_resolver_selects_legacy"),
]
_PC_TOOLS = {"device_id": "dev_" + "a" * 32, "allowed_scopes": ["files_list"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("with_resolver", _STREAM_SELECTIONS)
@pytest.mark.parametrize("pc_tools", [None, _PC_TOOLS], ids=["ordinary_turn", "pc_tools"])
async def test_resolver_setting_selects_bridge_and_stream_passes_first_record(
    monkeypatch, with_resolver, pc_tools,
) -> None:
    bridge, transport, resolver = _selected_stream_bridge(
        monkeypatch, with_resolver=with_resolver,
    )
    subject = CANONICAL_SUBJECT if with_resolver else PRODUCT_USER
    stream = bridge.start_stream(
        user_id=PRODUCT_USER, messages=[{"role": "user", "content": "Hello"}],
        skill=get_task_mode("auto"), model_id="b14/model", user_text="Hello",
        conversation_id=None, pc_tools=pc_tools, subject_id=subject, session_id="session_1",
    )
    try:
        first = await anext(stream)
        assert first["event"]["kind"] == "run_started"
        tail = [record async for record in stream]
        assert tail[-1]["result"].answer == "OK"
    finally:
        await stream.aclose()
    assert len(transport.calls) == 1
    payload = json.loads(transport.calls[0]["body"])
    assert payload["subject_id"] == subject
    if pc_tools is None:
        assert "pc_tools" not in payload
    else:
        assert payload["pc_tools"] == pc_tools
    assert transport.closed
    if resolver is not None:
        assert resolver.calls == [PRODUCT_USER]
        assert bridge._current_engine_subject.get() is None


@pytest.mark.parametrize("with_resolver", _STREAM_SELECTIONS)
def test_resolver_setting_selected_builder_pc_tools_none_preserves_request_bytes(
    monkeypatch, with_resolver,
) -> None:
    from app import orchestration_bridge as bridge_module

    monkeypatch.setattr(bridge_module.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    bridge, _transport, _resolver = _selected_stream_bridge(
        monkeypatch, with_resolver=with_resolver,
    )
    subject = CANONICAL_SUBJECT if with_resolver else PRODUCT_USER
    kwargs = dict(
        user_id=subject, messages=[{"role": "user", "content": "Hello"}],
        skill=get_task_mode("auto"), model_id="b14/model",
        conversation_id=None, subject_id=subject, session_id="session_1",
    )
    # The legacy builder is the existing wire contract; omission and explicit
    # None must match its full serialized bytes, including field ordering.
    baseline = B62EngineOrchestrationBridge.build_engine_request(**kwargs)
    token = bridge._current_engine_subject.set(subject) if with_resolver else None
    try:
        omitted = bridge.build_engine_request(**kwargs)
        explicit_none = bridge.build_engine_request(**kwargs, pc_tools=None)
    finally:
        if with_resolver:
            bridge._current_engine_subject.reset(token)
    encoded = [
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        for value in (baseline, omitted, explicit_none)
    ]
    assert encoded[0] == encoded[1] == encoded[2]
    assert "pc_tools" not in explicit_none


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["resolver_unavailable", "subject_mismatch"])
async def test_supplied_resolver_selects_canonical_stream_and_fails_closed_before_engine(
    monkeypatch, failure,
) -> None:
    from app.orchestration_bridge import B62OrchestrationError

    bridge, transport, resolver = _selected_stream_bridge(monkeypatch, with_resolver=True)
    if failure == "resolver_unavailable":
        async def unavailable(**kwargs):
            raise RuntimeError("identity authority unavailable")
        monkeypatch.setattr(resolver, "resolve_subject_id", unavailable)
    stream = bridge.start_stream(
        user_id=PRODUCT_USER, messages=[], skill=get_task_mode("auto"),
        model_id="b14/model", user_text="Hello", conversation_id=None, pc_tools=None,
        subject_id="subject:other" if failure == "subject_mismatch" else CANONICAL_SUBJECT,
        session_id="session_1",
    )
    try:
        with pytest.raises(B62OrchestrationError) as raised:
            await anext(stream)
    finally:
        await stream.aclose()
    assert raised.value.code == (
        "canonical_subject_mismatch" if failure == "subject_mismatch"
        else "control_plane_session_unavailable"
    )
    assert transport.calls == []
    assert bridge._current_engine_subject.get() is None


@pytest.mark.asyncio
async def test_supplied_resolver_selects_canonical_stream_and_early_close_clears_subject(
    monkeypatch,
) -> None:
    bridge, _transport, _resolver = _selected_stream_bridge(monkeypatch, with_resolver=True)
    # Isolate this wrapper's ownership of the inherited iterator. SDK decoder
    # finalization is a separate boundary, covered by its existing contracts.
    closed = []

    async def source(request, *, pc_progress):
        try:
            yield {"event": {"kind": "run_started"}}
        finally:
            closed.append(True)

    monkeypatch.setattr(bridge._client, "stream_orchestration", source)
    stream = bridge.start_stream(
        user_id=PRODUCT_USER, messages=[], skill=get_task_mode("auto"),
        model_id="b14/model", user_text="Hello", conversation_id=None, pc_tools=None,
        subject_id=CANONICAL_SUBJECT, session_id="session_1",
    )
    try:
        assert "event" in await anext(stream)
    finally:
        await stream.aclose()
    assert closed == [True]
    assert bridge._current_engine_subject.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('pc_tools', [None, _PC_TOOLS])
async def test_byok_production_selected_canonical_bridge_forwards_private_ref(monkeypatch, pc_tools):
    bridge, transport, resolver = _selected_stream_bridge(monkeypatch, with_resolver=True)
    ref = 'unit-opaque-reference-never-public'
    stream = bridge.start_stream(
        user_id=PRODUCT_USER, messages=[{'role':'user','content':'hello'}],
        skill=get_task_mode('auto'), model_id='google/unit-model', user_text='hello',
        conversation_id=None, subject_id=CANONICAL_SUBJECT if pc_tools else None,
        session_id='session_user_key', pc_tools=pc_tools,
        user_credential_ref=ref, byok_selection={'provider':'gemini','model':'unit-model'})
    records = [record async for record in stream]
    wire = json.loads(transport.calls[0]['body'])
    assert wire['subject_id'] == CANONICAL_SUBJECT
    assert wire['user_credential_ref'] == ref
    assert wire['max_retries'] == 0
    assert ref not in str(records[-1]['result'].orchestration)
    assert resolver.calls == [PRODUCT_USER]
    assert bridge._current_engine_subject.get() is None
