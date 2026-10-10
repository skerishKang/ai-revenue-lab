"""Worker binding helpers shared by the Cloudflare entrypoint and tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextvars import ContextVar, Token
from typing import Any

# None means no Worker request is active (local CLI/tests may use os.environ).
# Within a request, an absent binding is an explicit empty credential: never
# fall back to process-global values from an earlier isolate invocation.
_request_bindings: ContextVar[dict[str, str] | None] = ContextVar(
    "b14_worker_request_bindings", default=None
)


def bind_request_env(overrides: Mapping[str, str]) -> Token:
    """Scope each request's bindings, isolated from concurrent coroutines."""
    return _request_bindings.set(dict(overrides))


def reset_request_env(token: Token) -> None:
    """Drop request bindings even if an ASGI handler raises."""
    _request_bindings.reset(token)


def scoped_secret(binding_name: str) -> str | None:
    """Outside Worker scope return None; inside missing means fail-closed."""
    values = _request_bindings.get()
    return None if values is None else values.get(binding_name, "")



async def collect_env_overrides(
    env: Any,
    keys: Iterable[str],
) -> dict[str, str]:
    """Resolve configured Worker bindings without exposing secret metadata.

    Plain Worker vars are read directly. Secrets Store bindings expose an
    async ``get()`` method and must be resolved through it; stringifying the
    binding object would only capture runtime metadata, not the secret value.
    """
    overrides: dict[str, str] = {}
    for key in keys:
        value = getattr(env, key, None)
        if value is None:
            continue
        getter = getattr(value, "get", None)
        if callable(getter):
            value = await getter()
        if value is not None:
            overrides[key] = str(value)
    return overrides
