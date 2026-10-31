"""Host transport for the existing CONTROL_PLANE_IDENTITY session RPC.

Use the admission HTTPS transport's existing v2 signature and per-attempt
service id. This adapter does not issue sessions, grant entitlement, or replace
the identity authority used by the remote admission Worker.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from app.local_admission_binding import AdmissionBindingConfigError, HttpsAdmissionBinding

IDENTITY_ORIGIN_ENV = "PADIEM_ENGINE_LOCAL_IDENTITY_ORIGIN"
IDENTITY_SECRET_ENV = "PADIEM_ENGINE_LOCAL_IDENTITY_SECRET"


class HttpsIdentityBinding:
    """The identity session read used by worker_identity's scope authority."""

    def __init__(self, origin: str, secret: str, *, client: httpx.AsyncClient | None = None) -> None:
        try:
            # Reject malformed brackets/ports before the existing HTTPS check.
            urlsplit(origin).port
        except ValueError:
            raise AdmissionBindingConfigError("identity origin is invalid") from None
        self._rpc = HttpsAdmissionBinding(origin, secret, client=client)

    async def resolve_auth_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._rpc._call("resolve_auth_session", payload)
        except Exception:
            # No URL, upstream envelope, proof or secret escapes the transport.
            raise RuntimeError("identity authority is unavailable") from None


def identity_binding_for(values: Mapping[str, Any]) -> dict[str, Any]:
    """Missing or invalid host configuration leaves the authority unbound."""

    origin = str(values.get(IDENTITY_ORIGIN_ENV, "") or "").strip()
    secret = str(values.get(IDENTITY_SECRET_ENV, "") or "").strip()
    if not origin and not secret:
        return {}
    try:
        binding = HttpsIdentityBinding(origin, secret)
    except (AdmissionBindingConfigError, httpx.InvalidURL):
        return {}
    return {"CONTROL_PLANE_IDENTITY": binding}
