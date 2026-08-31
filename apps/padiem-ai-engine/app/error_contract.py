"""Canonical safe error taxonomy for the internal Padiem AI Engine.

This module is intentionally data-only. It defines the machine-readable error
contract shared by completed execution, provider-token streaming, and unified
orchestration surfaces without changing runtime behavior or authorizing blind
retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class RetryProtocol(str, Enum):
    """Client recovery protocol for an Engine error code."""

    NONE = "none"
    SAME_IDEMPOTENCY_KEY = "same_idempotency_key"
    SAME_CONTINUATION_REF = "same_continuation_ref"
    NEW_REQUEST_ALLOWED = "new_request_allowed"


@dataclass(frozen=True, slots=True)
class EngineErrorContract:
    code: str
    status_code: int
    safe_message: str
    retryable: bool
    retry_protocol: RetryProtocol
    surfaces: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _IDENTIFIER_RE.fullmatch(self.code):
            raise ValueError("error code must be a bounded safe identifier")
        if self.status_code < 400 or self.status_code > 599:
            raise ValueError("status_code must be a 4xx/5xx HTTP status")
        if not isinstance(self.safe_message, str) or not self.safe_message.strip():
            raise ValueError("safe_message is required")
        if not isinstance(self.retry_protocol, RetryProtocol):
            raise ValueError("retry_protocol must be RetryProtocol")
        if not isinstance(self.surfaces, tuple) or not self.surfaces:
            raise ValueError("surfaces must be a non-empty tuple")
        if self.retryable and self.retry_protocol is RetryProtocol.NONE:
            raise ValueError("retryable errors require an explicit recovery protocol")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "status_code": self.status_code,
            "safe_message": self.safe_message,
            "retryable": self.retryable,
            "retry_protocol": self.retry_protocol.value,
            "surfaces": list(self.surfaces),
        }


ENGINE_ERROR_TAXONOMY: tuple[EngineErrorContract, ...] = (
    EngineErrorContract(
        "invalid_request",
        400,
        "Request body is invalid.",
        False,
        RetryProtocol.NONE,
        ("execute", "stream", "orchestration"),
    ),
    EngineErrorContract(
        "invalid_json",
        400,
        "Request body must contain valid UTF-8 JSON.",
        False,
        RetryProtocol.NONE,
        ("execute", "stream", "orchestration"),
    ),
    EngineErrorContract(
        "unsupported_media_type",
        415,
        "Content-Type must be application/json.",
        False,
        RetryProtocol.NONE,
        ("execute", "stream", "orchestration"),
    ),
    EngineErrorContract(
        "request_too_large",
        413,
        "Request body exceeds the internal Engine safety limit.",
        False,
        RetryProtocol.NONE,
        ("execute", "stream", "orchestration"),
    ),
    EngineErrorContract(
        "b14_service_unavailable",
        503,
        "Business 14 service binding is unavailable.",
        True,
        RetryProtocol.NEW_REQUEST_ALLOWED,
        ("execute", "stream", "orchestration"),
    ),
    EngineErrorContract(
        "execution_context_unavailable",
        422,
        "Execution context is unavailable.",
        False,
        RetryProtocol.NONE,
        ("execute",),
    ),
    EngineErrorContract(
        "idempotency_conflict",
        409,
        "Idempotency key is already bound to a different execution request.",
        False,
        RetryProtocol.NONE,
        ("execute", "orchestration"),
    ),
    EngineErrorContract(
        "approval_verification_unavailable",
        503,
        "Approval decision verification is unavailable.",
        False,
        RetryProtocol.SAME_CONTINUATION_REF,
        ("orchestration_resume",),
    ),
    EngineErrorContract(
        "continuation_store_unavailable",
        503,
        "Approval continuation storage is unavailable.",
        False,
        RetryProtocol.SAME_CONTINUATION_REF,
        ("orchestration_run", "orchestration_resume", "orchestration_cancel"),
    ),
    EngineErrorContract(
        "invalid_continuation",
        409,
        "Continuation reference is invalid.",
        False,
        RetryProtocol.NONE,
        ("orchestration_resume", "orchestration_cancel"),
    ),
    EngineErrorContract(
        "continuation_claimed",
        409,
        "Continuation is already being resumed.",
        False,
        RetryProtocol.SAME_CONTINUATION_REF,
        ("orchestration_resume",),
    ),
    EngineErrorContract(
        "continuation_consumed",
        409,
        "Continuation has already been consumed.",
        False,
        RetryProtocol.NONE,
        ("orchestration_resume", "orchestration_cancel"),
    ),
    EngineErrorContract(
        "continuation_expired",
        409,
        "Continuation has expired.",
        False,
        RetryProtocol.NONE,
        ("orchestration_resume", "orchestration_cancel"),
    ),
    EngineErrorContract(
        "stream_idempotency_unavailable",
        422,
        "Streaming idempotency requires a product-owned replay adapter.",
        False,
        RetryProtocol.NONE,
        ("stream",),
    ),
    EngineErrorContract(
        "engine_internal_error",
        500,
        "Padiem AI Engine execution failed.",
        False,
        RetryProtocol.NONE,
        ("execute", "stream", "orchestration"),
    ),
)

_ENGINE_ERROR_BY_CODE = {item.code: item for item in ENGINE_ERROR_TAXONOMY}


def engine_error_contract(code: str) -> EngineErrorContract:
    if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
        raise ValueError("error code must be a bounded safe identifier")
    try:
        return _ENGINE_ERROR_BY_CODE[code]
    except KeyError:
        raise ValueError("unknown Engine error code") from None


def current_engine_error_taxonomy() -> tuple[EngineErrorContract, ...]:
    return ENGINE_ERROR_TAXONOMY
