"""Worker binding helpers shared by the Cloudflare entrypoint and tests.

Secrets Store bindings are retained as request-scoped handles, not eagerly read.
The first use of a specific credential resolves it exactly once in that request.
"""

from __future__ import annotations

import asyncio

from collections.abc import Iterable, Mapping
from contextvars import ContextVar, Token
from typing import Any

# None: local CLI / tests, which may use os.environ.
# Inside a Worker request a missing or unresolved binding always fails closed.
_request_bindings: ContextVar[dict[str, Any] | None] = ContextVar(
    "b14_worker_request_bindings", default=None
)


def bind_request_env(overrides: Mapping[str, Any]) -> Token:
    """Isolate bindings and resolved keys between concurrent requests."""
    return _request_bindings.set(dict(overrides))


def reset_request_env(token: Token) -> None:
    """Drop request bindings, resolved keys, and any stale secret references."""
    _request_bindings.reset(token)


def scoped_secret(binding_name: str) -> str | None:
    """Return a resolved credential; never turn a binding handle into a key."""
    values = _request_bindings.get()
    if values is None:
        return None
    value = values.get(binding_name, "")
    if callable(getattr(value, "get", None)):
        return ""  # Unresolved; the async caller must explicitly load it.
    return value if isinstance(value, str) else ""


async def load_request_secret(binding_name: str) -> None:
    """Resolve one Secrets Store binding at most once per active Worker request.

    Fail closed if the binding is missing or get() fails. Keys are never logged,
    put in global environment, or shared across concurrent Worker requests.
    """
    values = _request_bindings.get()
    if values is None:
        return
    value = values.get(binding_name, "")
    if isinstance(value, asyncio.Future):
        # A second coroutine in the same request shares the in-flight read.
        await asyncio.shield(value)
        return
    getter = getattr(value, "get", None)
    if not callable(getter):
        return  # Already resolved, or missing. Never use a global fallback.

    # Publish an in-flight marker before yielding to the binding getter.
    # No second coroutine observes a transient empty secret as final.
    in_flight = asyncio.get_running_loop().create_future()
    values[binding_name] = in_flight
    resolved = ""
    try:
        secret = await getter()
        resolved = str(secret) if secret is not None else ""
    except Exception:
        pass  # Missing/revoked bindings fail closed without retries.
    finally:
        values[binding_name] = resolved
        in_flight.set_result(resolved)


def collect_request_bindings(env: Any, keys: Iterable[str]) -> dict[str, Any]:
    """Collect request-scoped handles without calling Secrets Store.get()."""
    values: dict[str, Any] = {}
    for key in keys:
        value = getattr(env, key, None)
        if value is None:
            continue
        if callable(getattr(value, "get", None)):
            values[key] = value
        else:
            values[key] = str(value)
    return values


async def collect_env_overrides(env: Any, keys: Iterable[str]) -> dict[str, str]:
    """Legacy eager helper retained for isolated CLI tests, not Worker fetch."""
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
