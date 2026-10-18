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

# Value-free resolution status per binding, used only for bounded diagnostics.
# A resolution failure is not the same state as an unconfigured credential;
# conflating the two made a live outage indistinguishable from a missing key.
_request_secret_status: ContextVar[dict[str, str] | None] = ContextVar(
    "b14_worker_request_secret_status", default=None
)


def bind_request_env(overrides: Mapping[str, Any]) -> Token:
    """Isolate bindings and resolved keys between concurrent requests."""
    _request_secret_status.set({})
    return _request_bindings.set(dict(overrides))


def reset_request_env(token: Token) -> None:
    """Drop request bindings, resolved keys, and any stale secret references."""
    _request_bindings.reset(token)
    _request_secret_status.set(None)


def secret_status(binding_name: str) -> str:
    """Return a value-free diagnostic status for one request binding.

    Possible values: ``resolved``, ``empty``, ``missing``, or
    ``error:<token>``. Returns ``""`` outside a Worker request or before the
    binding is resolved. Never contains secret material.
    """
    statuses = _request_secret_status.get()
    if statuses is None:
        return ""
    return statuses.get(binding_name, "")


def _classify_binding_error(exc: BaseException) -> str:
    """Map a binding failure to a fixed vocabulary without retaining detail.

    The exception message is inspected only to select a token; it is never
    stored, logged, or returned, because binding errors may quote secret
    names, account identifiers, or provider material.
    """
    try:
        message = str(exc)[:500].lower()
    except Exception:
        message = ""
    if "not found" in message or "does not exist" in message:
        return "error:not_found"
    if "different request" in message:
        return "error:cross_request"
    if "permission" in message or "unauthorized" in message or "forbidden" in message:
        return "error:forbidden"
    if "not implemented" in message or "unsupported" in message:
        return "error:unsupported"
    js_name = getattr(exc, "name", "")
    if isinstance(js_name, str) and js_name.isalnum() and len(js_name) <= 32:
        return f"error:js_{js_name}"
    return f"error:{type(exc).__name__}"


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
    statuses = _request_secret_status.get()
    if binding_name not in values:
        if statuses is not None:
            statuses[binding_name] = "missing"
        return
    value = values[binding_name]
    if isinstance(value, asyncio.Future):
        # A second coroutine in the same request shares the in-flight read.
        await asyncio.shield(value)
        return
    getter = getattr(value, "get", None)
    if not callable(getter):
        if statuses is not None:
            if isinstance(value, str):
                statuses.setdefault(binding_name, "resolved" if value else "empty")
            else:
                statuses[binding_name] = "missing"
        return  # Already resolved, or missing. Never use a global fallback.

    # Publish an in-flight marker before yielding to the binding getter.
    # No second coroutine observes a transient empty secret as final.
    in_flight = asyncio.get_running_loop().create_future()
    values[binding_name] = in_flight
    resolved = ""
    _dbg_forms = []
    for _form, _call in (("noarg", lambda: getter()), ("empty", lambda: getter("")), ("name", lambda: getter(binding_name))):
        try:
            secret = await _call()
            resolved = str(secret) if secret is not None else ""
            import logging as _dbg_logging
            _dbg_logging.getLogger("b14dbg").warning("DBG_FORM_OK form=%s resolved_len=%d", _form, len(resolved))
            break
        except Exception as exc:
            import logging as _dbg_logging
            _dbg_logging.getLogger("b14dbg").warning("DBG_FORM_FAIL form=%s type=%s name=%s msg=%r", _form, type(exc).__name__, getattr(exc, "name", ""), str(exc)[:200])
            _dbg_forms.append(_form)
    if not resolved and len(_dbg_forms) == 3:
        # all forms failed
        if statuses is not None:
            statuses[binding_name] = "error:js_Error"
    else:
        if statuses is not None:
            statuses[binding_name] = "resolved" if resolved else "empty"
    try:
        pass
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
