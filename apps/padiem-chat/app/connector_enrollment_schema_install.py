"""One-shot enrollment schema install for shared PC enrollment (#4139).

The canonical Identity DO creates enrollment tables ONLY through the
reviewed `install_connector_enrollment_schema` RPC gated by the transient
worker flag `CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED`.
This module adds the smallest execution wiring for that one call inside the
existing owner enrollment composition. It is idempotent by construction
(`CREATE TABLE/INDEX IF NOT EXISTS`): calling it when the schema already
exists changes nothing and never reinstalls.

Hard boundaries (must stay true):

* EXPLICIT OPERATOR ACTION. B54 canonical session + CSRF + exact
  confirmation body, like every other enrollment mutation here.
* FIXED MIGRATION. The browser cannot choose a migration; the single
  reviewed id `connector-enrollment-v1` is the only accepted value and the
  receipt must echo it with `installed_by_default is False`.
* NO NEW AUTHORITY. Uses only the existing private Identity Service Binding
  client. No new server, table, worker, account, or auth system is created.
* NO TRANSIENT FLAG HERE. Enabling the install flag and turning it off
  afterwards is a separate Worker deploy concern, never a route behavior.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .claw_connector_enrollment_routes import (
    _consent_payload,
    _error,
    _json,
    _verified_owner_request,
)
from .control_plane_identity import IdentityBridgeError

ENROLLMENT_SCHEMA_INSTALL_PATH = "/api/claw/connector/enrollments/install-schema"
_SCHEMA_MIGRATION_ID = "connector-enrollment-v1"


async def install_enrollment_schema(request: Request) -> JSONResponse:
    """Run the reviewed enrollment schema migration exactly once per call."""
    session, denial = await _verified_owner_request(request)
    if denial is not None:
        return denial
    del session

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(authority, "install_connector_enrollment_schema", None)):
        return _error(503, "enrollment_server_dependency_unavailable")

    wire = await _consent_payload(request, frozenset({"confirmed", "confirmation_version"}))
    if (
        wire is None
        or wire.get("confirmed") is not True
        or wire.get("confirmation_version") != "pc-enrollment-consent-v1"
    ):
        return _error(400, "connector_owner_bootstrap_consent_required")

    try:
        receipt = await authority.install_connector_enrollment_schema(
            migration_id=_SCHEMA_MIGRATION_ID,
        )
    except IdentityBridgeError as exc:
        status = exc.status_code if exc.status_code in (400, 401, 403, 404, 409, 429, 503) else 503
        code = exc.code if isinstance(exc.code, str) and exc.code else "enrollment_server_dependency_unavailable"
        return _error(status, code)
    except Exception:
        return _error(503, "enrollment_server_dependency_unavailable")
    if (
        type(receipt) is not dict
        or receipt.get("schema") != _SCHEMA_MIGRATION_ID
        or receipt.get("installed_by_default") is not False
    ):
        return _error(503, "enrollment_server_dependency_unavailable")
    return _json(
        {"ok": True, "schema": _SCHEMA_MIGRATION_ID, "installed_by_default": False}, 200,
    )
