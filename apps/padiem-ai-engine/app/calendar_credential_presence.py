"""Private read-only Calendar credential-presence surface (#2010, G1 PLAN_A).

Purpose
-------
Before any Calendar OAuth re-connect is authorized, the Control Plane must be
asked one bounded question for one server-trusted workspace:

```text
does an existing reviewed google-calendar Control Plane credential exist?
```

The Control Plane already answers it through the private
``workspace_calendar_connector_state`` RPC, but no Engine caller existed, so the
RPC was unreachable without a production deploy. This module adds the smallest
reviewed read-only path that reaches it:

```text
Engine worker fetch()
  -> CONTROL_PLANE_GOOGLE_OAUTH Service Binding
  -> workspace_calendar_connector_state({"workspace_ref": ...})
  -> bounded four-fact projection
```

Boundary
--------
* Internal route only (``/internal/v1/...``), never a public route; the Engine's
  public edge is unchanged and ``service.py`` keeps no reference to this path.
* Gated by the existing operator token binding that already guards the
  caller-authority diagnostic, so no new secret is required or read.
* Payload is closed to exactly ``{"workspace_ref": ...}``: the caller can never
  choose a connector, scope, binding_ref, actor_ref, account_ref or provider id.
* Exactly one Service Binding call, no retry, no access lease, no token unseal,
  no D1 write, no provider call.
* The response carries only connector_id / state / usable / expires_present /
  ambiguous evidence. Raw calendar ids, refs, scopes, tokens, sealed material and
  the workspace ref itself are never emitted.
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Mapping
from typing import Any

CALENDAR_CREDENTIAL_PRESENCE_PATH = "/internal/v1/diagnostics/calendar-credential-presence"

# Reuses the operator token that already guards the runtime-internal authority
# diagnostic: same high-entropy gate, and no new production secret is needed.
PRESENCE_TOKEN_ENV = "PADIEM_ENGINE_AUTHORITY_DIAGNOSTIC_TOKEN"
PRESENCE_TOKEN_HEADER = "x-padiem-engine-authority-diagnostic-token"
MIN_PRESENCE_TOKEN_BYTES = 32
MAX_PRESENCE_TOKEN_BYTES = 512

PRESENCE_BINDING_NAME = "CONTROL_PLANE_GOOGLE_OAUTH"
PRESENCE_RPC_METHOD = "workspace_calendar_connector_state"
CALENDAR_PRESENCE_CONNECTOR_ID = "google-calendar"

MAX_PRESENCE_ENTRIES = 1
MAX_PRESENCE_BODY_BYTES = 4_096
MAX_PRESENCE_PAYLOAD_KEYS = 1

_WORKSPACE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BOUNDED_ENTRY_KEYS = frozenset(
    {"connector_id", "state", "usable", "expires_present", "ambiguous"}
)
_ALLOWED_STATES = ("not_connected", "connected", "ambiguous")

# Truth flags for the contract tests.
CALENDAR_PRESENCE_READ_ONLY = True
CALENDAR_PRESENCE_INTERNAL_ROUTE_ONLY = True
PUBLIC_ROUTE_ADDED = False
PAYLOAD_CLOSED = True
TOKEN_UNSEAL = False
ACCESS_LEASE_ISSUE = False
D1_MUTATION = False
PROVIDER_CALL = False
MAX_PRESENCE_RPC_ATTEMPTS = 1


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
            "metadata": None,
        },
    }


def _token_bytes(value: Any) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        return None


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        return None
    return value if isinstance(value, str) else None


def _closed_payload(raw: bytes | None) -> dict[str, Any] | None:
    """Parse the payload, which must be exactly {"workspace_ref": <safe ref>}."""

    if not raw:
        return None
    if len(raw) > MAX_PRESENCE_BODY_BYTES:
        return None
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict) or len(decoded) != MAX_PRESENCE_PAYLOAD_KEYS:
        return None
    if set(decoded) != {"workspace_ref"}:
        return None
    workspace_ref = decoded.get("workspace_ref")
    if not isinstance(workspace_ref, str) or _WORKSPACE_REF_RE.fullmatch(workspace_ref) is None:
        return None
    return {"workspace_ref": workspace_ref}


def project_presence(rpc_result: Any) -> dict[str, Any]:
    """Project the private RPC result into the bounded four-fact evidence.

    Any deviation from the reviewed envelope fails closed: the surface exists to
    answer presence, never to forward whatever the Control Plane returned.
    """

    if not isinstance(rpc_result, Mapping) or rpc_result.get("ok") is not True:
        raise ValueError("noncanonical presence envelope")
    connectors = rpc_result.get("connectors")
    if not isinstance(connectors, list) or len(connectors) > MAX_PRESENCE_ENTRIES:
        raise ValueError("presence entry list is not bounded")
    if not connectors:
        raise ValueError("presence entry is missing")

    entry = connectors[0]
    if not isinstance(entry, Mapping):
        raise ValueError("presence entry is not an object")
    if set(entry) - _BOUNDED_ENTRY_KEYS:
        raise ValueError("presence entry carries unbounded fields")
    if entry.get("connector_id") != CALENDAR_PRESENCE_CONNECTOR_ID:
        raise ValueError("presence entry is not the reviewed Calendar connector")

    state = entry.get("state")
    if state not in _ALLOWED_STATES:
        raise ValueError("presence state is not a reviewed value")
    usable = entry.get("usable")
    expires_present = entry.get("expires_present")
    ambiguous = entry.get("ambiguous")
    for value in (usable, expires_present, ambiguous):
        if not isinstance(value, bool):
            raise ValueError("presence flags must be boolean")

    # Fail closed on the same tri-state invariants the public projection uses.
    if state == "connected" and usable is not True:
        raise ValueError("connected presence must be usable")
    if state == "not_connected" and usable is not False:
        raise ValueError("not_connected presence must not be usable")
    if state == "ambiguous" and ambiguous is not True:
        raise ValueError("ambiguous presence must report ambiguity")

    return {
        "CALENDAR_CREDENTIAL_PRESENCE_STATE": state,
        "CALENDAR_CREDENTIAL_USABLE": "YES" if usable else "NO",
        "CALENDAR_CREDENTIAL_EXPIRES_PRESENT": "YES" if expires_present else "NO",
        "CALENDAR_CREDENTIAL_AMBIGUOUS": "YES" if ambiguous else "NO",
    }


def presence_locks() -> dict[str, str]:
    """Fixed evidence locks emitted with every bounded presence answer."""

    return {
        "PRESENCE_READ_MODE": "PRIVATE_RPC",
        "PRESENCE_READ_ATTEMPT": "1",
        "TOKEN_UNSEAL": "0",
        "ACCESS_LEASE_ISSUE": "0",
        "D1_MUTATION": "0",
        "PROVIDER_CALL": "0",
        "PUBLIC_ROUTE_ADDED": "NO",
        "PAYLOAD_CLOSED": "YES",
        "RAW_REF_OUTPUT": "0",
        "RAW_TOKEN_OUTPUT": "0",
        "RAW_WORKSPACE_REF_OUTPUT": "0",
        "CALLER_SELECTED_CONNECTOR": "0",
    }


async def read_calendar_presence(env: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Perform exactly one private read for the reviewed Calendar connector."""

    binding = getattr(env, PRESENCE_BINDING_NAME, None)
    method = getattr(binding, PRESENCE_RPC_METHOD, None)
    if not callable(method):
        raise RuntimeError("calendar presence surface is not configured")
    try:
        result = await method({"workspace_ref": payload["workspace_ref"]})
    except Exception:
        raise RuntimeError("calendar presence read failed") from None
    return project_presence(result)


async def calendar_presence_response(
    env: Any,
    method: str | None,
    headers: Any,
    raw_body: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    """Authorize and answer one bounded Calendar presence request."""

    if str(method or "").upper() != "POST":
        return 405, _error("method_not_allowed", "Method not allowed.")

    server_token = _token_bytes(getattr(env, PRESENCE_TOKEN_ENV, None))
    if (
        server_token is None
        or not MIN_PRESENCE_TOKEN_BYTES <= len(server_token) <= MAX_PRESENCE_TOKEN_BYTES
    ):
        return 503, _error(
            "calendar_presence_unavailable",
            "Calendar credential presence read is not configured.",
        )
    presented_token = _token_bytes(_header_value(headers, PRESENCE_TOKEN_HEADER))
    if presented_token is None or len(presented_token) > MAX_PRESENCE_TOKEN_BYTES:
        return 401, _error(
            "calendar_presence_unauthorized",
            "Calendar presence authorization is invalid.",
        )
    if not hmac.compare_digest(presented_token, server_token):
        return 401, _error(
            "calendar_presence_unauthorized",
            "Calendar presence authorization is invalid.",
        )

    payload = _closed_payload(raw_body)
    if payload is None:
        return 400, _error(
            "invalid_request",
            "Calendar presence payload must contain exactly the reviewed workspace reference.",
        )

    try:
        projected = await read_calendar_presence(env, payload)
    except RuntimeError:
        return 503, _error(
            "calendar_presence_unavailable",
            "Calendar credential presence read is unavailable.",
        )
    except ValueError:
        return 502, _error(
            "calendar_presence_noncanonical",
            "Calendar credential presence read returned a noncanonical response.",
        )

    body: dict[str, Any] = {"ok": True}
    body.update(projected)
    body.update(presence_locks())
    return 200, body
