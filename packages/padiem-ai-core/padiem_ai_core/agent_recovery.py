"""Fail-closed orchestration recovery semantics for P01 Agent Runtime.

Recovery here is deliberately narrower than Provider routing/fallback. Business
14 remains responsible for Provider retries/fallback. Core may only decide
whether a trusted, explicitly classified orchestration-driver failure can retry
one step. Tool failures are never automatically retried because the ToolRuntime
may have crossed an external side-effect boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


MAX_AGENT_STEP_RETRIES = 4
MAX_RECOVERY_CODE_COUNT = 32
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AgentRecoveryError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("agent recovery error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise AgentRecoveryError(
            "invalid_agent_recovery_contract",
            f"{name} must be a bounded safe identifier",
        )
    return value


class AgentFailureSource(str, Enum):
    ORCHESTRATION_DRIVER = "orchestration_driver"
    TOOL_RUNTIME = "tool_runtime"
    PROVIDER = "provider"
    POLICY = "policy"
    UNKNOWN = "unknown"


class AgentRecoveryAction(str, Enum):
    RETRY_STEP = "retry_step"
    FAIL_RUN = "fail_run"


@dataclass(frozen=True, slots=True)
class AgentFailure:
    """Normalized failure evidence used only for recovery policy decisions."""

    source: AgentFailureSource
    code: str
    safe_message: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, AgentFailureSource):
            raise AgentRecoveryError(
                "invalid_agent_recovery_contract",
                "failure source must be AgentFailureSource",
            )
        object.__setattr__(self, "code", _identifier("failure code", self.code))
        if not isinstance(self.safe_message, str) or not self.safe_message.strip():
            raise AgentRecoveryError(
                "invalid_agent_recovery_contract",
                "safe_message must be a non-empty string",
            )
        message = self.safe_message.strip()
        if len(message) > 1_000:
            raise AgentRecoveryError(
                "invalid_agent_recovery_contract",
                "safe_message exceeds the bounded recovery limit",
            )
        object.__setattr__(self, "safe_message", message)

    def to_public_dict(self) -> dict[str, str]:
        return {
            "source": self.source.value,
            "code": self.code,
            "message": self.safe_message,
        }


@dataclass(frozen=True, slots=True)
class AgentRecoveryPolicy:
    """Trusted server policy for retrying orchestration-driver failures only."""

    retryable_driver_codes: tuple[str, ...] = ()
    max_retries_per_step: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.retryable_driver_codes, (str, bytes)):
            raise AgentRecoveryError(
                "invalid_agent_recovery_policy",
                "retryable_driver_codes must be a tuple of identifiers",
            )
        codes = tuple(
            _identifier("retryable driver code", code)
            for code in self.retryable_driver_codes
        )
        if len(codes) > MAX_RECOVERY_CODE_COUNT:
            raise AgentRecoveryError(
                "invalid_agent_recovery_policy",
                "retryable_driver_codes exceeds the bounded policy size",
            )
        if len(set(codes)) != len(codes):
            raise AgentRecoveryError(
                "invalid_agent_recovery_policy",
                "retryable_driver_codes must not contain duplicates",
            )
        object.__setattr__(self, "retryable_driver_codes", codes)
        if (
            isinstance(self.max_retries_per_step, bool)
            or not isinstance(self.max_retries_per_step, int)
            or not 0 <= self.max_retries_per_step <= MAX_AGENT_STEP_RETRIES
        ):
            raise AgentRecoveryError(
                "invalid_agent_recovery_policy",
                f"max_retries_per_step must be between 0 and {MAX_AGENT_STEP_RETRIES}",
            )


@dataclass(frozen=True, slots=True)
class AgentRecoveryContext:
    """Trusted runtime facts used to prevent unsafe retry after side effects."""

    step_index: int
    retries_used: int
    external_side_effect_since_checkpoint: bool = False

    def __post_init__(self) -> None:
        for name in ("step_index", "retries_used"):
            value = getattr(self, name)
            minimum = 1 if name == "step_index" else 0
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < minimum
            ):
                raise AgentRecoveryError(
                    "invalid_agent_recovery_context",
                    f"{name} must be an integer >= {minimum}",
                )
        if not isinstance(self.external_side_effect_since_checkpoint, bool):
            raise AgentRecoveryError(
                "invalid_agent_recovery_context",
                "external_side_effect_since_checkpoint must be boolean",
            )


@dataclass(frozen=True, slots=True)
class AgentRecoveryDecision:
    action: AgentRecoveryAction
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, AgentRecoveryAction):
            raise AgentRecoveryError(
                "invalid_agent_recovery_decision",
                "action must be AgentRecoveryAction",
            )
        object.__setattr__(self, "reason", _identifier("recovery reason", self.reason))

    def to_public_dict(self) -> dict[str, str]:
        return {"action": self.action.value, "reason": self.reason}


def decide_agent_recovery(
    failure: AgentFailure,
    context: AgentRecoveryContext,
    *,
    policy: AgentRecoveryPolicy | None = None,
) -> AgentRecoveryDecision:
    """Return a bounded recovery decision without executing the retry itself.

    Provider failures always terminate at this layer so Core never becomes a
    second B14 router/fallback implementation. ToolRuntime failures also
    terminate because blindly repeating a tool can duplicate external effects.
    """

    if not isinstance(failure, AgentFailure):
        raise AgentRecoveryError(
            "invalid_agent_recovery_contract",
            "failure must be AgentFailure",
        )
    if not isinstance(context, AgentRecoveryContext):
        raise AgentRecoveryError(
            "invalid_agent_recovery_context",
            "context must be AgentRecoveryContext",
        )
    active_policy = policy or AgentRecoveryPolicy()
    if not isinstance(active_policy, AgentRecoveryPolicy):
        raise AgentRecoveryError(
            "invalid_agent_recovery_policy",
            "policy must be AgentRecoveryPolicy",
        )

    if failure.source is AgentFailureSource.PROVIDER:
        return AgentRecoveryDecision(
            AgentRecoveryAction.FAIL_RUN,
            "provider_recovery_belongs_to_b14",
        )
    if failure.source is AgentFailureSource.TOOL_RUNTIME:
        return AgentRecoveryDecision(
            AgentRecoveryAction.FAIL_RUN,
            "tool_failure_not_auto_retryable",
        )
    if failure.source is AgentFailureSource.POLICY:
        return AgentRecoveryDecision(
            AgentRecoveryAction.FAIL_RUN,
            "policy_failure_not_retryable",
        )
    if failure.source is not AgentFailureSource.ORCHESTRATION_DRIVER:
        return AgentRecoveryDecision(
            AgentRecoveryAction.FAIL_RUN,
            "unknown_failure_not_retryable",
        )
    if context.external_side_effect_since_checkpoint:
        return AgentRecoveryDecision(
            AgentRecoveryAction.FAIL_RUN,
            "side_effect_boundary_blocks_retry",
        )
    if failure.code not in active_policy.retryable_driver_codes:
        return AgentRecoveryDecision(
            AgentRecoveryAction.FAIL_RUN,
            "driver_failure_not_allowlisted",
        )
    if context.retries_used >= active_policy.max_retries_per_step:
        return AgentRecoveryDecision(
            AgentRecoveryAction.FAIL_RUN,
            "step_retry_budget_exhausted",
        )

    return AgentRecoveryDecision(
        AgentRecoveryAction.RETRY_STEP,
        "trusted_driver_retry_allowed",
    )
