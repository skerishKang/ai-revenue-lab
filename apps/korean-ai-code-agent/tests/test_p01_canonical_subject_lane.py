"""#3382 — canonical USER subject lane for the P01 wire.

The Claw P01 path used to pin ``subject_id=None`` and the Engine client
rejected ANY subject outright, so an authenticated user's canonical identity
never reached A7 admission. The reviewed lane flips both sides together, and
only together:

- The factory accepts an optional ``subject_id`` but ONLY when its lane flag is
  on; a subject on the default lane is still a hard error.
- The Engine client serializes the subject only under the same lane and still
  rejects every other authority field.
- The adapter propagates one flag to factory and client, so they can never
  disagree, and exposes ``subject_identity_lane`` for the caller.
"""

from __future__ import annotations

import pytest

from kagent.p01_adapter import (
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01RequestFactory,
)
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from kagent.contracts import ClawTaskIntent, ExecutionMode
from kagent.runs import ClawRun

CANONICAL_SUBJECT = "sub_" + "c" * 32
OTHER_SUBJECT = "sub_" + "d" * 32


def _run() -> ClawRun:
    intent = ClawTaskIntent(
        task_id="task_p01_lane",
        task="Summarize overnight alerts",
        repository_ref="skerishKang/example",
        execution_mode=ExecutionMode.LOCAL,
    )
    return ClawRun.create("claw_run_1", intent)


class _RecordingClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def orchestrate(self, payload):
        self.payloads.append(payload)
        return {"result": {"answer": "ok"}, "run": {"status": "completed"}}


def _factory(*, lane: bool) -> P01RequestFactory:
    return P01RequestFactory(allow_subject_identity=lane)


def _client(*, lane: bool) -> tuple[P01EngineOrchestrationClient, _RecordingClient]:
    recording = _RecordingClient()
    return P01EngineOrchestrationClient(recording, allow_subject_identity=lane), recording


# ── factory contract ────────────────────────────────────────────────────────


def test_default_factory_lane_is_off() -> None:
    # The default factory keeps the historical subjectless contract.
    bundle = _factory(lane=False).build(_run())
    assert bundle.orchestration_request.subject_id is None


def test_subject_on_default_lane_is_a_hard_error() -> None:
    with pytest.raises(P01AdapterError) as exc:
        _factory(lane=False).build(_run(), subject_id=CANONICAL_SUBJECT)
    assert exc.value.code == "p01_authority_field_unsupported"


def test_canonical_lane_accepts_a_canonical_subject() -> None:
    bundle = _factory(lane=True).build(_run(), subject_id=CANONICAL_SUBJECT)
    assert bundle.orchestration_request.subject_id == CANONICAL_SUBJECT


def test_canonical_lane_preserves_absent_subject() -> None:
    bundle = _factory(lane=True).build(_run())
    assert bundle.orchestration_request.subject_id is None


@pytest.mark.parametrize("bad", ["", "   ", " sub_abc", "x" * 257, 123, True, ["sub_x"]])
def test_canonical_lane_rejects_malformed_subject(bad) -> None:
    with pytest.raises(P01AdapterError):
        _factory(lane=True).build(_run(), subject_id=bad)


def test_factory_lane_flag_must_be_boolean() -> None:
    with pytest.raises(P01AdapterError):
        P01RequestFactory(allow_subject_identity="yes")  # type: ignore[arg-type]


# ── Engine client contract ──────────────────────────────────────────────────


def test_default_client_still_rejects_any_subject() -> None:
    from padiem_ai_core import OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hi"},),
            trace_id="tr_x",
        ),
        context=_context(),
        app_id="b54-padiem-claw",
        subject_id=CANONICAL_SUBJECT,
    )
    with pytest.raises(P01AdapterError) as exc:
        _client(lane=False)[0]._reject_unsupported_authority(request)
    assert exc.value.code == "p01_authority_field_unsupported"


@pytest.mark.parametrize(
    "bad_subject",
    [
        "usr_abc",                        # product-user id is not a subject
        "usr_" + "1" * 32,
        "sub_",                           # no hex body
        "sub_" + "c" * 31,                # short
        "sub_" + "c" * 33,                # long
        "sub_" + "C" * 32,                # uppercase hex
        "tenant_" + "a" * 32,             # tenant id is not a subject
        "b54-padiem-claw",
        "sub_" + "c" * 31 + "-",           # non-hex character
        "sub_" + "c" * 32 + "x",           # suffix garbage (core's safe-id allows it; the canonical grammar does not)
    ],
)
def test_canonical_client_rejects_non_canonical_subjects(bad_subject: str) -> None:
    """#3382: the client enforces the SAME canonical grammar as the factory.

    The Engine client receives an ``OrchestrationRequest`` directly and never
    passes through ``P01RequestFactory``, so a bounded-but-not-canonical
    subject (for example a ``usr_*`` product id) must still fail closed here.
    Without this check a caller holding a request object could smuggle a
    non-canonical subject onto the wire.
    """
    from padiem_ai_core import OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hi"},),
            trace_id="tr_x",
        ),
        context=_context(),
        app_id="b54-padiem-claw",
        subject_id=bad_subject,
    )
    # The rejection runs through both the authority gate and the payload build,
    # so a bypass of either one still fails closed.
    with pytest.raises(P01AdapterError) as exc:
        _client(lane=True)[0]._reject_unsupported_authority(request)
    assert exc.value.code == "invalid_subject_id"
    with pytest.raises(P01AdapterError) as exc:
        _client(lane=True)[0]._build_payload(request)
    assert exc.value.code == "invalid_subject_id"


@pytest.mark.parametrize(
    "malformed",
    [
        " sub_" + "c" * 32,               # leading space
        "sub_" + "c" * 32 + "\n",         # trailing newline
        "",
    ],
)
def test_core_orchestration_rejects_malformed_subject_before_the_lane(malformed: str) -> None:
    """Core's own bounded-identifier check runs first, ahead of the canonical lane.

    These shapes never reach ``P01RequestFactory`` or the Engine client: the
    shared Core contract refuses them at ``OrchestrationRequest`` construction.
    """
    from padiem_ai_core import OrchestrationError, OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    with pytest.raises(OrchestrationError):
        OrchestrationRequest(
            execution_request=ExecutionRequest(
                agent=_agent_profile(),
                messages=({"role": "user", "content": "hi"},),
                trace_id="tr_x",
            ),
            context=_context(),
            app_id="b54-padiem-claw",
            subject_id=malformed,
        )


def test_canonical_client_accepts_a_canonical_subject() -> None:
    from padiem_ai_core import OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hi"},),
            trace_id="tr_x",
        ),
        context=_context(),
        app_id="b54-padiem-claw",
        subject_id=CANONICAL_SUBJECT,
    )
    _client(lane=True)[0]._reject_unsupported_authority(request)


def test_canonical_client_serializes_the_subject() -> None:
    from padiem_ai_core import OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    client, _ = _client(lane=True)
    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hi"},),
            trace_id="tr_x",
        ),
        context=_context(),
        app_id="b54-padiem-claw",
        subject_id=CANONICAL_SUBJECT,
    )
    payload = client._build_payload(request)
    assert payload["subject_id"] == CANONICAL_SUBJECT


def test_default_client_never_serializes_a_subject() -> None:
    from padiem_ai_core import OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    client, _ = _client(lane=False)
    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hi"},),
            trace_id="tr_x",
        ),
        context=_context(),
        app_id="b54-padiem-claw",
        subject_id=None,
    )
    payload = client._build_payload(request)
    assert "subject_id" not in payload


def test_client_enable_subject_identity_toggles_the_lane() -> None:
    client, _ = _client(lane=False)
    client.enable_subject_identity(True)
    from padiem_ai_core import OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hi"},),
            trace_id="tr_x",
        ),
        context=_context(),
        app_id="b54-padiem-claw",
        subject_id=CANONICAL_SUBJECT,
    )
    client._reject_unsupported_authority(request)


# ── adapter propagation ─────────────────────────────────────────────────────


def test_adapter_propagates_one_lane_flag_to_factory_and_client() -> None:
    client, _ = _client(lane=False)
    adapter = P01CoreOrchestrationAdapter(client, allow_subject_identity=True)
    # The adapter turned the client's lane on, and the factory inherited it.
    bundle = adapter._factory.build(_run(), subject_id=CANONICAL_SUBJECT)
    assert bundle.orchestration_request.subject_id == CANONICAL_SUBJECT
    from padiem_ai_core import OrchestrationRequest
    from padiem_ai_core.execution_runtime import ExecutionRequest
    from kagent.p01_adapter import _agent_profile

    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hi"},),
            trace_id="tr_x",
        ),
        context=_context(),
        app_id="b54-padiem-claw",
        subject_id=OTHER_SUBJECT,
    )
    client._reject_unsupported_authority(request)


def test_adapter_exposes_the_lane_flag() -> None:
    client, _ = _client(lane=False)
    off = P01CoreOrchestrationAdapter(client)
    on = P01CoreOrchestrationAdapter(_client(lane=False)[0], allow_subject_identity=True)
    assert off.subject_identity_lane is False
    assert on.subject_identity_lane is True


def test_adapter_lane_flag_must_be_boolean() -> None:
    client, _ = _client(lane=False)
    with pytest.raises(P01AdapterError):
        P01CoreOrchestrationAdapter(client, allow_subject_identity=1)  # type: ignore[arg-type]


def _context():
    from padiem_ai_core.execution_context import ExecutionContext

    return ExecutionContext(trace_id="tr_x", idempotency_key=None, timeout_seconds=20.0)
