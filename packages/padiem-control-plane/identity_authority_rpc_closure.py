"""#7542 P1-A: one place that closes identity RPCs with no identified caller.

The RPC definitions stay in place so a rollback only has to remove a name from
``CLOSED_IDENTITY_RPC_METHODS``. The private Service Binding and the COM2
ingress list both derive their behaviour from this set.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

CLOSED_IDENTITY_RPC_METHODS: frozenset[str] = frozenset({
    "get_tenant",
    "revoke_tenant_membership",
})
IDENTITY_AUTHORITY_RPC_CLOSED = "identity_authority_rpc_closed"
_CLOSED_MESSAGE = "Canonical identity request was rejected"


def closed_identity_rpc_response() -> dict[str, Any]:
    """The existing canonical rejection envelope, with a dedicated code."""

    return {
        "ok": False,
        "error": {
            "code": IDENTITY_AUTHORITY_RPC_CLOSED,
            "message": _CLOSED_MESSAGE,
        },
    }


def retire_closed_identity_rpc(
    handler: Callable[[Any, dict], Awaitable[dict[str, Any]]],
) -> Callable[[Any, dict], Awaitable[dict[str, Any]]]:
    """Refuse a closed method before its body, store or upstream is reached."""

    method_name = handler.__name__

    @wraps(handler)
    async def guarded(self, payload: dict) -> dict[str, Any]:
        if method_name in CLOSED_IDENTITY_RPC_METHODS:
            return closed_identity_rpc_response()
        return await handler(self, payload)

    return guarded


def without_closed_identity_rpcs(methods: frozenset[str]) -> frozenset[str]:
    """The active HTTPS surface for one ingress."""

    return methods - CLOSED_IDENTITY_RPC_METHODS
