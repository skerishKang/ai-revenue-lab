"""#3139 — project a bounded Local Runner terminal result into its Claw conversation.

A Local Runner task is created from a Claw conversation, executed on the Desktop
and acknowledged by the canonical broker. This module is the missing return leg:
the terminal outcome goes back to the conversation that started it, exactly once.

It owns no new authority. The conversation is the one already linked on the
existing `claw_run_history` origin row, the append is one write on the existing
history authority, and the only facts it consumes are the canonical broker's own
correlation — `command_id`, `run_id`, `tool_request_ref`, `request_id`,
`revision_ref`, `evidence_ref` and `request_fingerprint`. The browser and the
device never choose the destination: the destination is read from the origin row.

Nothing here can express raw material. The observation contract has no field for
argv, stdout, stderr, a credential or an approval payload, so a projection that
tried to carry one would not type-check.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Protocol

from .history import (
    HistoryError,
    HistoryForbidden,
    MAX_RUN_RESULT_SUMMARY_CHARS,
    validate_conversation_id,
)

#: Only these canonical broker states carry a terminal fact worth returning.
PROJECTABLE_STATES = frozenset({"acknowledged", "expired"})
_ACKNOWLEDGED = "acknowledged"
_EXPIRED = "expired"
_MAX_CONTENT_CHARS = 1_000
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXECUTION_TERMINATIONS = frozenset({"exited", "cancelled", "timed_out"})


class LocalTaskResultError(RuntimeError):
    """A fail-closed refusal carrying a deterministic code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _ref(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise LocalTaskResultError("local_task_result_invalid_correlation", f"{name} must be a bounded safe reference")
    return value


def _digest(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise LocalTaskResultError("local_task_result_invalid_correlation", f"{name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class LocalRunnerTerminalObservation:
    """One bounded terminal fact read from the canonical broker.

    Every field is a server-owned correlation or a bounded outcome. There is
    deliberately no field for command material: raw argv, stdout, stderr,
    device credentials and approval payloads cannot be represented here, so they
    cannot reach a conversation projection by accident.
    """

    command_id: str
    run_id: str
    tool_request_ref: str
    request_id: str
    revision_ref: str
    evidence_ref: str | None
    request_fingerprint: str
    sequence: int
    state: str
    termination: str | None = None
    exit_code: int | None = None
    acknowledged_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("command_id", "run_id", "tool_request_ref", "request_id", "revision_ref"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        object.__setattr__(self, "request_fingerprint", _digest("request_fingerprint", self.request_fingerprint))
        if self.evidence_ref is not None:
            object.__setattr__(self, "evidence_ref", _ref("evidence_ref", self.evidence_ref))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise LocalTaskResultError("local_task_result_invalid_correlation", "sequence must be a positive integer")
        if not isinstance(self.state, str) or self.state not in PROJECTABLE_STATES:
            raise LocalTaskResultError("local_task_result_invalid_correlation", "state must be a projectable canonical state")
        if self.termination is not None and self.termination not in _EXECUTION_TERMINATIONS:
            raise LocalTaskResultError("local_task_result_invalid_correlation", "termination must be a bounded execution termination")
        if self.exit_code is not None and (isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)):
            raise LocalTaskResultError("local_task_result_invalid_correlation", "exit_code must be a bounded integer or null")
        if self.state == _EXPIRED and (self.termination is not None or self.exit_code is not None):
            # An EXPIRED reconciliation proves no execution. Carrying a
            # termination or exit code here would invent one.
            raise LocalTaskResultError("local_task_result_fabricated_execution", "an expired command cannot carry an execution outcome")
        if self.state == _ACKNOWLEDGED and self.termination is None:
            raise LocalTaskResultError("local_task_result_invalid_correlation", "an acknowledged command must carry its bounded outcome")
        if self.acknowledged_at is not None and (not isinstance(self.acknowledged_at, str) or len(self.acknowledged_at) > 64):
            raise LocalTaskResultError("local_task_result_invalid_correlation", "acknowledged_at must be a bounded timestamp")

    @property
    def executed(self) -> bool:
        return self.state == _ACKNOWLEDGED and self.termination is not None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "run_id": self.run_id,
            "tool_request_ref": self.tool_request_ref,
            "request_id": self.request_id,
            "revision_ref": self.revision_ref,
            "evidence_ref": self.evidence_ref,
            "request_fingerprint": self.request_fingerprint,
            "sequence": self.sequence,
            "state": self.state,
            "termination": self.termination,
            "exit_code": self.exit_code,
            "acknowledged_at": self.acknowledged_at,
            "raw_argv": False,
            "raw_stdout": False,
            "raw_stderr": False,
            "raw_device_credential": False,
            "p01_approval_payload": False,
        }


@dataclass(frozen=True, slots=True)
class LocalTaskOrigin:
    """The server-owned origin: the run row's own conversation linkage."""

    user_id: str
    run_id: str
    conversation_id: str
    workspace_id: str | None = None


class TrustedLocalRunnerResultPort(Protocol):
    """The only source of terminal facts: the canonical broker, read-only.

    Deliberately not a command-authority port. This module cannot enqueue,
    admit, acknowledge or reconcile anything.
    """

    async def command_result(self, *, command_id: str) -> LocalRunnerTerminalObservation | None:
        ...


def result_message_id(*, conversation_id: str, command_id: str, revision_ref: str) -> str:
    """A deterministic message id: the store's exactly-once key.

    The same terminal fact always produces the same id, so re-running the
    projection after a lost response, a duplicate observation or a restart
    collides on the ``messages.id`` primary key instead of appending again.
    """

    payload = json.dumps(
        {"v": 1, "conversation_id": conversation_id, "command_id": command_id, "revision_ref": revision_ref},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "msg_ltr_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


@dataclass(frozen=True, slots=True)
class LocalTaskResultDecision:
    """What one observation requires. Pure data, decided without any write."""

    append: bool
    message_id: str
    content: str
    summary: str
    status: str
    reason: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "append": self.append,
            "message_id": self.message_id,
            "content": self.content,
            "summary": self.summary,
            "status": self.status,
            "reason": self.reason,
            "executed": self.status == "completed",
        }


def decide_local_task_result(*, origin: LocalTaskOrigin, observation: LocalRunnerTerminalObservation) -> LocalTaskResultDecision:
    """Pure: what one terminal observation means for one origin conversation.

    Correlation is checked before anything is rendered, so a command that belongs
    to another run, and an origin with no conversation, both fail closed before a
    single character is written.
    """

    if not isinstance(origin, LocalTaskOrigin) or not isinstance(observation, LocalRunnerTerminalObservation):
        raise LocalTaskResultError("local_task_result_invalid_input", "origin and observation are required")
    if not isinstance(origin.user_id, str) or not origin.user_id:
        raise LocalTaskResultError("local_task_result_no_origin", "origin has no owning account")
    conversation_id = validate_conversation_id(origin.conversation_id)
    if not conversation_id:
        raise LocalTaskResultError("local_task_result_no_origin", "origin has no originating conversation")
    if observation.run_id != origin.run_id:
        raise LocalTaskResultError(
            "local_task_result_run_mismatch",
            "the terminal command belongs to a different run than the originating conversation",
        )

    message_id = result_message_id(
        conversation_id=conversation_id,
        command_id=observation.command_id,
        revision_ref=observation.revision_ref,
    )
    if observation.executed:
        content = (
            f"로컬 러너 작업이 종료되었습니다. "
            f"상태: {observation.termination}, 종료 코드: {observation.exit_code}, "
            f"명령: {observation.command_id}."
        )
        summary = f"exited/{observation.exit_code}"
        status = "completed"
    else:
        # EXPIRED proves no execution happened. The projection says exactly that
        # and reports no termination and no exit code.
        content = (
            f"로컬 러너 작업 결과가 기록되지 않았습니다. "
            f"명령: {observation.command_id}, 사유: 기한 만료(실행 결과 없음)."
        )
        summary = "expired/no-result"
        status = "expired"
    if len(content) > _MAX_CONTENT_CHARS:
        raise LocalTaskResultError("local_task_result_not_bounded", "projected content exceeds its bound")
    if len(summary) > MAX_RUN_RESULT_SUMMARY_CHARS:
        raise LocalTaskResultError("local_task_result_not_bounded", "projected summary exceeds its bound")
    return LocalTaskResultDecision(
        append=True,
        message_id=message_id,
        content=content,
        summary=summary,
        status=status,
        reason="terminal observation for the originating conversation",
    )


async def project_local_runner_terminal_result(
    *,
    history: Any,
    result_port: TrustedLocalRunnerResultPort,
    user_id: str,
    run_id: str,
    command_id: str,
    expected_workspace_id: str | None = None,
) -> LocalTaskResultDecision:
    """Project one terminal Local Runner result into the run's own conversation.

    The destination is read from the origin row, never taken from the caller, and
    the append is the history authority's single idempotent write. Calling this
    twice for the same terminal fact — after a lost response, a duplicate
    observation, or a restart reread — returns the second decision without
    appending a second message.
    """

    if not isinstance(user_id, str) or not user_id:
        raise LocalTaskResultError("local_task_result_no_origin", "user_id is required")
    row = await history.get_claw_run(user_id, run_id)
    if row is None:
        # Never discloses whether another owner's run exists.
        raise HistoryForbidden("claw run is not owned by current user")
    workspace_id = row.get("workspace_id")
    if expected_workspace_id is not None and workspace_id is not None and workspace_id != expected_workspace_id:
        raise LocalTaskResultError(
            "local_task_result_workspace_mismatch",
            "the run belongs to a different workspace than the caller expects",
        )
    origin = LocalTaskOrigin(
        user_id=user_id,
        run_id=run_id,
        conversation_id=row.get("conversation_id"),
        workspace_id=workspace_id,
    )
    observation = await result_port.command_result(command_id=command_id)
    if observation is None:
        return LocalTaskResultDecision(
            append=False,
            message_id="",
            content="",
            summary="",
            status="pending",
            reason="no canonical terminal result is available yet",
        )
    if observation.command_id != command_id:
        raise LocalTaskResultError("local_task_result_command_mismatch", "the observation is for a different command")
    decision = decide_local_task_result(origin=origin, observation=observation)
    appended = await history.append_local_task_result(
        user_id=user_id,
        run_id=run_id,
        message_id=decision.message_id,
        summary=decision.summary,
        content=decision.content,
        status=decision.status,
    )
    if not appended:
        return LocalTaskResultDecision(
            append=False,
            message_id=decision.message_id,
            content=decision.content,
            summary=decision.summary,
            status=decision.status,
            reason="the identical result was already durable in the originating conversation",
        )
    return decision


CANONICAL_TERMINAL_RESULT_CONSUMER = True
SERVER_OWNED_ORIGIN_CORRELATION = True
ORIGIN_CONVERSATION_CHOSEN_BY_CALLER = False
ORIGIN_CONVERSATION_READ_FROM_RUN_ROW = True
DUPLICATE_APPEND_SUPPRESSED_BY_STORE = True
EXPIRED_FABRICATES_EXECUTION = False
RAW_MATERIAL_IN_PROJECTION = False
SECOND_CONVERSATION_AUTHORITY = False
SECOND_RESULT_AUTHORITY = False
BROKER_COMMAND_AUTHORITY = False
BROKER_STATE_WRITTEN = False
DEVICE_LIFECYCLE_PROJECTION_TOUCHED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
