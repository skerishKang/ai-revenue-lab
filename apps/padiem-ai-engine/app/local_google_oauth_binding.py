"""Host transport for the existing CONTROL_PLANE_GOOGLE_OAUTH binding (#7229).

On Cloudflare the Engine reaches the Google OAuth state authority through a
private Service Binding and calls one reviewed method for the Calendar lane:
``select_calendar_binding`` (``app/calendar_read_activation.py``). A CPython
host has no Service Binding, so this module turns that same call into the
already-reviewed HTTPS RPC contract — the v2 service proof and per-attempt
service id that ``app/local_admission_binding.HttpsAdmissionBinding`` uses for
the admission and identity lanes.

Nothing new is introduced: no second signature scheme, no second ingress
secret, no credential store. The secret this adapter signs with is the state
Worker's own ingress secret — the same value Chat's host already holds as
``PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET`` — and the state Worker exposes the
method only once its reviewed HTTPS allow-list includes it.

Absent or malformed configuration leaves the binding unbound, exactly like
``identity_binding_for``: the Engine then keeps its own fail-closed
``503 calendar_activation_unavailable`` instead of a fabricated authority.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from app.local_admission_binding import AdmissionBindingConfigError, HttpsAdmissionBinding

GOOGLE_OAUTH_ORIGIN_ENV = "PADIEM_ENGINE_LOCAL_GOOGLE_OAUTH_ORIGIN"
GOOGLE_OAUTH_SECRET_ENV = "PADIEM_ENGINE_LOCAL_GOOGLE_OAUTH_SECRET"


class HttpsGoogleOAuthBinding:
    """The Calendar binding-selection read used by ``CloudflareCalendarBindingClient``."""

    def __init__(self, origin: str, secret: str, *, client: httpx.AsyncClient | None = None) -> None:
        try:
            # Reject malformed brackets/ports before the existing HTTPS check.
            urlsplit(origin).port
        except ValueError:
            raise AdmissionBindingConfigError("google oauth origin is invalid") from None
        self._rpc = HttpsAdmissionBinding(origin, secret, client=client)

    async def select_calendar_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One reviewed read: which Calendar binding a workspace may use.

        The payload is closed by the Worker to exactly ``workspace_ref``, and the
        Worker answers only ``status``/``connector_id``/``workspace_ref``/
        ``binding_ref``/``actor_ref``. This adapter adds nothing to either side
        and never logs the request, the response or the secret.
        """

        try:
            return await self._rpc._call("select_calendar_binding", payload)
        except Exception:
            # No URL, upstream envelope, proof or secret escapes the transport.
            raise RuntimeError("google oauth authority is unavailable") from None


def google_oauth_binding_for(values: Mapping[str, Any]) -> dict[str, Any]:
    """Missing or invalid host configuration leaves the authority unbound."""

    origin = str(values.get(GOOGLE_OAUTH_ORIGIN_ENV, "") or "").strip()
    secret = str(values.get(GOOGLE_OAUTH_SECRET_ENV, "") or "").strip()
    if not origin and not secret:
        return {}
    try:
        binding = HttpsGoogleOAuthBinding(origin, secret)
    except (AdmissionBindingConfigError, httpx.InvalidURL):
        return {}
    return {"CONTROL_PLANE_GOOGLE_OAUTH": binding}


__all__ = [
    "GOOGLE_OAUTH_ORIGIN_ENV",
    "GOOGLE_OAUTH_SECRET_ENV",
    "HttpsGoogleOAuthBinding",
    "google_oauth_binding_for",
]
