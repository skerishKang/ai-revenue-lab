"""#4139 — deterministic producer + real Claw consumer race regression.

CENTRAL reproduced a lost-message race against LOCAL1 HEAD ``8fe3b8ea``:

```text
successful ACK -> private RPC {'ok': True, 'available': False, 'kind': 'other'}
               -> Claw persists a bodyless terminal-only message under the
                  stable message id -> the real TXT arrives -> the identical
                  append is ignored -> PERSISTED_MESSAGES=1, text lost
```

The message id the consumer derives is ``(conversation_id, command_id,
revision_ref)`` and the history append is an insert against its primary key, so
whichever projection writes first owns the id. This test runs the **real**
canonical Broker — the in-memory SQLite Durable Object fixture, the
authenticated device HTTP handler and the private read RPC — together with the
**real** Claw consumer ``project_local_runner_terminal_result`` from
``apps/padiem-chat/app/claw_local_task_result_projection.py`` and a history fake
that enforces the identical exactly-once message id.

Three couplings are pinned here:

1. the fixed order (intent -> real read -> ACK -> body) never consumes the
   message id before the text exists;
2. a device that skips the intent still loses the text — that is the producer
   ordering obligation CENTRAL asked LOCAL2 to confirm, not a Broker guarantee;
3. a refused private read fails closed: no terminal-only message is fabricated.

Nothing here uploads, deploys or contacts a real Broker.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
CHAT_APP = REPO / "apps" / "padiem-chat"
if str(CHAT_APP) not in sys.path:
    sys.path.insert(0, str(CHAT_APP))

from app.claw_local_task_result_projection import (  # noqa: E402  (path setup above)
    LocalRunnerTerminalObservation,
    LocalTaskResultError,
    project_local_runner_terminal_result,
)
from test_local_agent_broker_text_results_4139 import (  # noqa: E402  (test-suite fixture)
    AUTHORITY_REF,
    BASE,
    COMMAND_ID,
    CREDENTIAL,
    KOREAN_TEXT,
    RUN_ID,
    ordered_fixture,
    stage,
)

USER_ID = "account.http.1"
WORKSPACE_ID = "workspace.http.1"
#: The real history validator requires the canonical ``chat_`` + 32 hex shape.
CONVERSATION_ID = "chat_" + "4" * 32
DURABLE_REASON = (
    "the identical result was already durable in the originating conversation"
)


class ExactlyOnceHistory:
    """The append contract the projection depends on, reduced to its key rule.

    The real store inserts the message under the id derived from the projection
    identity and reports ``False`` when that id is already durable. A different
    body for the same id therefore never overwrites the first one; it is simply
    ignored, which is exactly how the reproduced race loses the text.
    """

    def __init__(self) -> None:
        self.messages: dict[str, str] = {}
        self.summaries: dict[str, str] = {}
        self.appends = 0
        self.ignored = 0

    async def get_claw_run(self, user_id: str, run_id: str):
        if user_id != USER_ID or run_id != RUN_ID:
            return None
        return {"workspace_id": WORKSPACE_ID, "conversation_id": CONVERSATION_ID}

    async def get_local_task_correlation(self, user_id: str, run_id: str):
        raise AssertionError("the test binds the correlation explicitly")

    async def append_local_task_result(
        self, *, user_id: str, run_id: str, message_id: str,
        summary: str, content: str, status: str,
    ) -> bool:
        if message_id in self.messages:
            self.ignored += 1
            return False
        self.messages[message_id] = content
        self.summaries[message_id] = summary
        self.appends += 1
        return True

    @property
    def contents(self) -> tuple[str, ...]:
        return tuple(self.messages.values())


class RealBrokerResultPort:
    """The two reads of ``claw_local_task_result_composition``, over real state."""

    def __init__(self, built: SimpleNamespace) -> None:
        self._built = built

    def _command(self):
        snapshot = self._built.store._state.load(authority_ref=AUTHORITY_REF).snapshot
        found = [item for item in snapshot.commands if item.command_id == COMMAND_ID]
        assert len(found) == 1
        return found[0]

    def correlation(self) -> dict[str, str]:
        command = self._command()
        return {
            "command_id": command.command_id,
            "tool_request_ref": command.tool_request_ref,
            "request_id": command.request_id,
            "revision_ref": command.revision_ref,
            "evidence_ref": command.evidence_ref,
            "request_fingerprint": command.request_fingerprint,
        }

    async def command_result(self, *, command_id, run_id, owner_id, workspace_id=None):
        command = self._command()
        if command_id != command.command_id:
            return None
        if command.state.value not in {"acknowledged", "expired"}:
            # No canonical terminal fact yet: the real composition returns None
            # and the projection appends nothing.
            return None
        return LocalRunnerTerminalObservation(
            command_id=command.command_id,
            run_id=command.run_id,
            tool_request_ref=command.tool_request_ref,
            request_id=command.request_id,
            revision_ref=command.revision_ref,
            evidence_ref=command.evidence_ref,
            request_fingerprint=command.request_fingerprint,
            sequence=command.sequence,
            state=command.state.value,
            termination=command.termination,
            exit_code=command.exit_code,
            acknowledged_at=(
                None if command.acknowledged_at is None
                else command.acknowledged_at.isoformat()
            ),
        )

    async def read_verified_file_text(self, *, owner_id, workspace_id, run_id, command_id):
        from local_agent_broker_text_results import read_verified_file_text_rpc

        return read_verified_file_text_rpc(self._built.store, {
            "account_ref": owner_id, "workspace_ref": workspace_id,
            "run_id": run_id, "command_id": command_id,
        })


def bound_history(port: RealBrokerResultPort) -> ExactlyOnceHistory:
    """A history whose stored correlation is the canonical one, as in production."""

    history = ExactlyOnceHistory()
    correlation = port.correlation()

    async def correlation_reader(user_id: str, run_id: str):
        if user_id != USER_ID or run_id != RUN_ID:
            return None
        return dict(correlation)

    history.get_local_task_correlation = correlation_reader  # type: ignore[method-assign]
    return history


def _run(coro):
    """This package has no pytest-asyncio, so coroutines run explicitly."""

    return asyncio.run(coro)


def poll(history, port):
    return _run(project_local_runner_terminal_result(
        history=history, result_port=port, user_id=USER_ID,
        run_id=RUN_ID, command_id=COMMAND_ID,
    ))


def ack(built) -> None:
    """The successful terminal ACK, issued after the intent was published."""

    built.authority.acknowledge(
        session_id=built.session.session_id, binding_ref=built.binding_ref,
        credential=CREDENTIAL,
        command_id=built.command.command_id,
        admission_ref="admission.text.4139", evidence_ref="evidence.text.4139",
        revision_ref=built.command.revision_ref, termination="exited",
        request_id="request.text.4139", exit_code=0,
        now=BASE + timedelta(seconds=4),
    )


def test_the_fixed_order_never_consumes_the_message_id_before_the_text():
    """intent -> real read -> ACK -> body: the text lands under the stable id."""

    built = ordered_fixture(ack=False)
    port = RealBrokerResultPort(built)
    history = bound_history(port)

    # 1. The device publishes the intent and awaits broker success FIRST.
    intent = stage(built.service, state="pending")
    assert intent["status"] == 200
    assert intent["body"]["text_result"]["state"] == "pending"

    # 2. Only then does the successful ACK land.
    ack(built)

    # 3. The first ACK-visible Claw poll must hold instead of completing.
    first = poll(history, port)
    assert first.status == "pending"
    assert first.append is False
    assert history.messages == {}, "a bodyless completed message was consumed"

    # 4. The real PC text is uploaded after the successful execution.
    body = stage(built.service)
    assert body["status"] == 200

    # 5. The next poll appends the real text under the same stable id.
    second = poll(history, port)
    assert second.append is True
    assert second.status == "completed"
    assert KOREAN_TEXT in second.content
    assert len(history.messages) == 1
    assert KOREAN_TEXT in history.contents[0]

    # 6. Re-querying and a duplicate upload never produce a second message.
    third = poll(history, port)
    assert third.append is False
    assert third.reason == DURABLE_REASON
    duplicate = stage(built.service)
    assert duplicate["status"] == 200
    assert duplicate["body"]["text_result"]["reused"] is True
    fourth = poll(history, port)
    assert fourth.append is False
    assert len(history.messages) == 1
    assert history.appends == 1


def test_a_device_that_skips_the_intent_still_loses_the_text():
    """The reproduced CENTRAL sequence, kept as the producer ordering obligation.

    The Broker cannot invent a task type: with no registered intent and a
    durable terminal fact it must answer the generic shape. This test exists so
    no one claims the race is closed for a producer that never declares its
    intent — LOCAL2 must publish ``state=pending`` and await broker success
    before the ACK.
    """

    built = ordered_fixture()  # already ACKNOWLEDGED, exit 0
    port = RealBrokerResultPort(built)
    history = bound_history(port)

    first = poll(history, port)
    assert first.append is True and first.status == "completed"
    assert KOREAN_TEXT not in first.content
    assert len(history.messages) == 1

    assert stage(built.service)["status"] == 200  # the text does arrive afterwards
    late = poll(history, port)
    assert late.append is False and late.reason == DURABLE_REASON
    assert len(history.messages) == 1
    assert KOREAN_TEXT not in history.contents[0]


def test_a_refused_private_read_never_fabricates_a_terminal_message():
    """Fail closed: a revoked binding yields no message, not a false completion."""

    built = ordered_fixture()
    port = RealBrokerResultPort(built)
    history = bound_history(port)
    built.authority.revoke_binding(
        binding_ref=built.binding_ref, now=BASE + timedelta(seconds=20),
    )

    with pytest.raises(LocalTaskResultError) as refused:
        poll(history, port)
    assert refused.value.code == "file_text_unverified"
    assert history.messages == {}


def test_an_intent_without_a_terminal_fact_appends_nothing():
    """The truthful wait: intent published, execution not finished yet."""

    built = ordered_fixture(ack=False)
    port = RealBrokerResultPort(built)
    history = bound_history(port)
    assert stage(built.service, state="pending")["status"] == 200

    decision = poll(history, port)
    assert decision.append is False
    assert decision.status == "pending"
    assert history.messages == {}
