from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Protocol

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")

MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 60.0


class IdempotencyConflictError(RuntimeError):
    """Raised when one idempotency key is reused for a different request."""


class IdempotencyAdapter(Protocol):
    """Product/server-owned storage contract for execution idempotency."""

    async def begin(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Any: ...

    async def complete(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        result: Mapping[str, Any],
    ) -> None: ...


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty safe identifier")
    return value


def _safe_idempotency_key(value: str) -> str:
    if not isinstance(value, str) or not _IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise ValueError("idempotency_key must be a bounded safe identifier")
    return value


def _normalize_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout_seconds must be numeric")
    timeout = float(value)
    if timeout < MIN_TIMEOUT_SECONDS or timeout > MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS:g} and {MAX_TIMEOUT_SECONDS:g}"
        )
    return timeout


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported value in execution fingerprint: {type(value)!r}")


def request_fingerprint(payload: Mapping[str, Any]) -> str:
    """Return a deterministic SHA-256 fingerprint of a JSON-like request."""
    if not isinstance(payload, Mapping):
        raise ValueError("fingerprint payload must be a mapping")
    canonical = _canonicalize(payload)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Canonical execution metadata.

    ``trace_id`` is observability metadata, not authorization.
    ``idempotency_key`` is replay identity, not authorization.
    ``timeout_seconds`` is a bounded execution budget.
    """

    trace_id: str
    idempotency_key: str | None = None
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _safe_identifier("trace_id", self.trace_id))
        if self.idempotency_key is not None:
            object.__setattr__(
                self,
                "idempotency_key",
                _safe_idempotency_key(self.idempotency_key),
            )
        object.__setattr__(self, "timeout_seconds", _normalize_timeout(self.timeout_seconds))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timeout_seconds": self.timeout_seconds,
            "idempotency_present": self.idempotency_key is not None,
        }
