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
