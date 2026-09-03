"""Canonical logical-execution fingerprint binding for Engine idempotency.

Core owns the material field classification and idempotency lifecycle semantics.
Engine keeps only the context-bound adapter shim needed to substitute the
canonical fingerprint at its service boundary.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
import inspect
from typing import Any

from padiem_ai_core.logical_execution_identity import (
    canonical_logical_execution_fingerprint,
)


_CANONICAL_IDEMPOTENCY_FINGERPRINT: ContextVar[str | None] = ContextVar(
    "padiem_engine_canonical_idempotency_fingerprint",
    default=None,
)


def _validate_fingerprint(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("canonical idempotency fingerprint must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("canonical idempotency fingerprint must be a sha256 hex digest") from exc
    return value.lower()


def set_canonical_idempotency_fingerprint(value: str) -> Token[str | None]:
    return _CANONICAL_IDEMPOTENCY_FINGERPRINT.set(_validate_fingerprint(value))


def reset_canonical_idempotency_fingerprint(token: Token[str | None]) -> None:
    _CANONICAL_IDEMPOTENCY_FINGERPRINT.reset(token)


def current_canonical_idempotency_fingerprint() -> str | None:
    return _CANONICAL_IDEMPOTENCY_FINGERPRINT.get()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class CanonicalFingerprintIdempotencyAdapter:
    """Delegate Core idempotency lifecycle calls using one canonical fingerprint.

    Optional adapter extensions such as ``abort``/``release`` are deliberately
    forwarded through ``__getattr__`` unchanged. Only fingerprint-bearing
    reserve/complete operations are normalized.
    """

    def __init__(self, delegate: Any) -> None:
        if delegate is None or not callable(getattr(delegate, "begin", None)):
            raise ValueError("delegate must provide begin()")
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    @staticmethod
    def _effective_fingerprint(fallback: str) -> str:
        canonical = current_canonical_idempotency_fingerprint()
        return canonical if canonical is not None else fallback

    async def begin(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Any:
        return await _maybe_await(
            self._delegate.begin(
                app_id=app_id,
                idempotency_key=idempotency_key,
                request_fingerprint=self._effective_fingerprint(request_fingerprint),
            )
        )

    async def complete(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        result: Any,
    ) -> None:
        method = getattr(self._delegate, "complete", None)
        if not callable(method):
            method = getattr(self._delegate, "commit", None)
        if not callable(method):
            raise RuntimeError("idempotency delegate does not provide complete/commit")
        await _maybe_await(
            method(
                app_id=app_id,
                idempotency_key=idempotency_key,
                request_fingerprint=self._effective_fingerprint(request_fingerprint),
                result=result,
            )
        )

    async def commit(self, **kwargs: Any) -> None:
        await self.complete(**kwargs)


def wrap_idempotency_adapter(delegate: Any | None) -> Any | None:
    if delegate is None:
        return None
    if isinstance(delegate, CanonicalFingerprintIdempotencyAdapter):
        return delegate
    return CanonicalFingerprintIdempotencyAdapter(delegate)
