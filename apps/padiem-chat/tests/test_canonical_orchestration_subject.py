from __future__ import annotations

import asyncio

import pytest

from app.canonical_orchestration_bridge import CanonicalSubjectB62EngineOrchestrationBridge
from app.control_plane_identity import IdentityBridgeError
from app.orchestration_bridge import B62OrchestrationError, OrchestrationSnapshot
from app.task_modes import get_task_mode

PRODUCT_USER = "usr_0123456789abcdef0123456789abcdef"
CANONICAL_SUBJECT = "subject:padiem:user:canonical-123"
CONTINUATION_REF = "cont_abcdefgh12345678"


def _event(kind: str, sequence: int) -> dict:
    return {
        "event_id": f"evt_{sequence}",
        "run_id": "run_1",
        "trace_id": "trace_1",
        "app_id": "padiem-chat",
        "kind": kind,
        "sequence": sequence,
    }


def _paused_raw() -> dict:
    return {
        "events": [_event("run_started", 1), _event("approval_paused", 2)],
        "approval_pause": {
            "status": "paused",
            "continuation_id": "pause_1",
            "requirement": "user_confirmation",
            "expires_at": "2099-01-01T01:00:00+00:00",
        },
        "continuation_ref": CONTINUATION_REF,
    }


def _completed_raw() -> dict:
    return {
        "execution": {"answer": "완료"},
        "events": [
            _event("run_started", 1),
            _event("run_resumed", 2),
            _event("run_completed", 3),
        ],
        "approval_pause": None,
    }


class FakeClient:
    def __init__(self) -> None:
        self.orchestrate_request = None
        self.resume_request = None

    async def orchestrate(self, request):
        self.orchestrate_request = dict(request)
        return _paused_raw()

    async def resume_orchestration(self, request):
        self.resume_request = dict(request)
        return _completed_raw()


class FakeStore:
    def __init__(self) -> None:
        self.snapshot = None
        self.saved = []
        self.decisions = []
        self.states = []

    async def save_pause(self, **kwargs):
        self.saved.append(kwargs)
        self.snapshot = OrchestrationSnapshot(
            continuation_ref=kwargs["continuation_ref"],
            user_id=kwargs["user_id"],
            pause_id=kwargs["pause_id"],
            engine_request=dict(kwargs["engine_request"]),
            user_text=kwargs["user_text"],
            conversation_id=kwargs["conversation_id"],
            expires_at=kwargs["expires_at"],
            state="active",
        )

    async def load_active(self, *, user_id, continuation_ref):
        if (
            self.snapshot is None
            or self.snapshot.user_id != user_id
            or self.snapshot.continuation_ref != continuation_ref
        ):
            raise B62OrchestrationError(
                "continuation_not_available",
                "이 작업은 더 이상 이어갈 수 없습니다.",
                status_code=409,
            )
        return self.snapshot

    async def record_decision(self, **kwargs):
        self.decisions.append(kwargs)

    async def set_state(self, **kwargs):
        self.states.append(kwargs)


class Resolver:
    def __init__(self, subject=CANONICAL_SUBJECT, error=None) -> None:
        self.subject = subject
        self.error = error
        self.calls = []

    async def resolve_subject_id(self, *, product_user_id):
        self.calls.append(product_user_id)
        if self.error is not None:
            raise self.error
        return self.subject


def _bridge(resolver=None):
    client = FakeClient()
    store = FakeStore()
    resolver = resolver or Resolver()
    bridge = CanonicalSubjectB62EngineOrchestrationBridge(
        client=client,
        store=store,
        canonical_subject_resolver=resolver,
    )
    return bridge, client, store, resolver


def _start(bridge):
    return asyncio.run(
        bridge.start(
            user_id=PRODUCT_USER,
            messages=[{"role": "user", "content": "질문"}],
            skill=get_task_mode("auto"),
            model_id="kilo/minimax-minimax-m3-free",
            user_text="질문",
            conversation_id="chat_0123456789abcdef0123456789abcdef",
        )
    )


def test_start_uses_canonical_subject_for_engine_but_product_user_for_local_owner() -> None:
    bridge, client, store, resolver = _bridge()

    _start(bridge)

    assert resolver.calls == [PRODUCT_USER]
    assert client.orchestrate_request["subject_id"] == CANONICAL_SUBJECT
    assert store.saved[0]["user_id"] == PRODUCT_USER
    assert store.saved[0]["engine_request"]["subject_id"] == CANONICAL_SUBJECT
    assert store.snapshot.user_id == PRODUCT_USER
    assert store.snapshot.engine_request["subject_id"] == CANONICAL_SUBJECT


def test_resolver_failure_stops_before_engine_and_local_pause_write() -> None:
    resolver = Resolver(
        error=IdentityBridgeError(
            401,
            "control_plane_session_inactive",
            "Canonical auth session is expired or revoked.",
        )
    )
    bridge, client, store, resolver = _bridge(resolver)

    with pytest.raises(B62OrchestrationError) as raised:
        _start(bridge)

    assert raised.value.status_code == 401
    assert raised.value.code == "control_plane_session_inactive"
    assert resolver.calls == [PRODUCT_USER]
    assert client.orchestrate_request is None
    assert store.saved == []


@pytest.mark.parametrize(
    "subject",
    [
        "unsafe subject with spaces",
        "x" * 129,
        "",
    ],
)
def test_invalid_or_engine_incompatible_canonical_subject_fails_closed(subject) -> None:
    bridge, client, store, resolver = _bridge(Resolver(subject=subject))

    with pytest.raises(B62OrchestrationError) as raised:
        _start(bridge)

    assert raised.value.status_code == 503
    assert raised.value.code == "canonical_subject_invalid"
    assert client.orchestrate_request is None
    assert store.saved == []


def test_resume_refreshes_same_canonical_subject_and_preserves_product_local_decision_owner() -> None:
    bridge, client, store, resolver = _bridge()
    _start(bridge)

    result = asyncio.run(
        bridge.resume(
            user_id=PRODUCT_USER,
            continuation_ref=CONTINUATION_REF,
            pause_id="pause_1",
            outcome="approved",
        )
    )

    assert resolver.calls == [PRODUCT_USER, PRODUCT_USER]
    assert client.resume_request is not None
    assert client.resume_request["subject_id"] == CANONICAL_SUBJECT
    assert client.resume_request["continuation_ref"] == CONTINUATION_REF
    assert store.decisions[0]["snapshot"].user_id == PRODUCT_USER
    assert store.decisions[0]["authority_ref"] == f"b62_session:{PRODUCT_USER}"
    assert result.answer == "완료"


def test_resume_subject_change_rejects_before_decision_state_mutation_or_engine_call() -> None:
    resolver = Resolver()
    bridge, client, store, resolver = _bridge(resolver)
    _start(bridge)
    resolver.subject = "subject:padiem:user:other-456"

    with pytest.raises(B62OrchestrationError) as raised:
        asyncio.run(
            bridge.resume(
                user_id=PRODUCT_USER,
                continuation_ref=CONTINUATION_REF,
                pause_id="pause_1",
                outcome="approved",
            )
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "canonical_subject_mismatch"
    assert resolver.calls == [PRODUCT_USER, PRODUCT_USER]
    assert client.resume_request is None
    assert store.decisions == []
    assert store.states == []
    assert store.snapshot.state == "active"


def test_product_user_never_becomes_canonical_subject_in_canonical_mode() -> None:
    bridge, client, store, _ = _bridge()
    _start(bridge)

    assert client.orchestrate_request["subject_id"] != PRODUCT_USER
    assert store.snapshot.user_id == PRODUCT_USER
