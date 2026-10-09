"""#3650 — the local/nonprod composition of the connect initiating leg.

Mirrors the established trusted-composition pattern
(``claw_local_access_composition``): the connect port exists only when the
nonprod run composition explicitly builds one. This module is never imported
into the production Worker root; even if it were, the port it builds is bound
to a **loopback** #3140 evidence host and an explicit TEST owner allowlist, and
the app factory installs nothing unless the composition root passes the port
in.

Authority boundary
------------------
* The minted-for principal is fixed at composition time: the real authenticated
  TEST account/workspace the #3140 host was started with. No request input can
  widen, replace or re-scope it — the request body carries at most a
  conversation id for envelope correlation.
* The canonical scope rule is reused, not bypassed: the port sends the composed
  principal as the challenge body and the #3140 host authenticates its own
  injected principal for the mint (``_handle_pairing_challenge`` refuses any
  body/auth mismatch with the canonical ``scope_mismatch``).
* Loopback only. A base URL that is not ``127.0.0.1`` / ``localhost`` / ``::1``
  fails composition: this port must never be born pointing at a deployed
  broker.
* ONE call. ``issue_pairing_challenge`` performs a single challenge POST; no
  retry loop exists that could mint twice for one user action.

Contract markers
----------------
``NONPROD_EVIDENCE_HOST_ONLY = True``
``LOOPBACK_ONLY = True``
``PRINCIPAL_SOURCE = "nonprod_composition_test_account"``
``OWNER_SCOPE_SOURCE = "server_session_identity_allowlist"``
``REQUEST_BODY_IS_AUTHORITY = False``
``CANONICAL_MINT_REUSED_NOT_REIMPLEMENTED = True``
``PRODUCTION_PAIRING_STORE_ADDED = False``
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping

__all__ = [
    "NonprodBrokerPairingConnectPort",
    "build_nonprod_claw_local_connect_port",
]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_CHALLENGE_ROUTE = "/v1/broker/pairings/challenge"
_REQUEST_TIMEOUT_SECONDS = 10
_MAX_RESPONSE_BYTES = 16 * 1024
_ALLOWED_TTL_SECONDS = 300


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class NonprodBrokerPairingConnectPort:
    """One canonical challenge mint over the loopback #3140 evidence host.

    The port speaks the exact canonical challenge contract
    (``padiem_control_plane.local_agent_broker_pairing_http``): a closed
    four-key body, an authenticated caller, and the closed five-key response.
    It owns no pairing state and persists nothing.
    """

    configured = True

    def __init__(
        self,
        *,
        broker_base_url: str,
        account_ref: str,
        workspace_ref: str,
        allowed_owner_ids: tuple[str, ...],
        now_factory: Any = None,
    ) -> None:
        from urllib.parse import urlsplit

        if not isinstance(broker_base_url, str) or not broker_base_url.startswith("http://"):
            raise ValueError("the nonprod connect port reaches a loopback http evidence host")
        split = urlsplit(broker_base_url)
        if (
            (split.hostname or "") not in _LOOPBACK_HOSTS
            or split.username is not None
            or split.password is not None
            or split.query
            or split.fragment
        ):
            raise ValueError("the nonprod connect port must be a bare loopback origin")
        if not split.path or split.path == "/":
            base = broker_base_url.rstrip("/")
        else:
            raise ValueError("the nonprod connect port base URL must be a bare origin")
        if not account_ref or not workspace_ref:
            raise ValueError("the nonprod connect port requires an explicit test principal")
        owners = tuple(owner for owner in allowed_owner_ids if isinstance(owner, str) and owner)
        if not owners:
            raise ValueError("the nonprod connect port requires a non-empty owner allowlist")
        self._base_url = base
        self._account_ref = account_ref
        self._workspace_ref = workspace_ref
        self.allowed_owner_ids = frozenset(owners)
        self._now_factory = now_factory or (
            lambda: datetime.now(timezone.utc).replace(microsecond=0)
        )

    def issue_pairing_challenge(
        self,
        *,
        owner_id: str,
        conversation_id: str | None,
        now: datetime,
    ) -> Mapping[str, Any] | None:
        """Exactly one canonical challenge POST; never a retry."""

        del conversation_id  # correlation only; never part of the canonical mint
        # The trusted composition's owner allowlist applies even to direct port
        # callers. A route-only check is insufficient for an injected port.
        if owner_id not in self.allowed_owner_ids:
            return None
        body = json.dumps(
            {
                "account_ref": self._account_ref,
                "workspace_ref": self._workspace_ref,
                "now": now.isoformat(),
                "ttl_seconds": _ALLOWED_TTL_SECONDS,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}{_CHALLENGE_ROUTE}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            # Do not allow a local evidence host to redirect a pairing mint
            # to a public endpoint or another owner-controlled service.
            with urllib.request.build_opener(_NoRedirect()).open(
                request, timeout=_REQUEST_TIMEOUT_SECONDS
            ) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                status = response.status
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if status != 200 or len(raw) > _MAX_RESPONSE_BYTES:
            return None
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(decoded, dict) or decoded.get("ok") is not True:
            return None
        challenge = decoded.get("challenge")
        if (
            not isinstance(challenge, dict)
            or challenge.get("account_ref") != self._account_ref
            or challenge.get("workspace_ref") != self._workspace_ref
        ):
            # Never send an OS deeplink for a mint in another owner/workspace.
            return None
        return decoded


def build_nonprod_claw_local_connect_port(
    *,
    broker_base_url: str,
    account_ref: str,
    workspace_ref: str,
    allowed_owner_ids: tuple[str, ...],
) -> NonprodBrokerPairingConnectPort | None:
    """Compose the port, or ``None`` when the inputs are not a valid nonprod set."""

    try:
        return NonprodBrokerPairingConnectPort(
            broker_base_url=broker_base_url,
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            allowed_owner_ids=allowed_owner_ids,
        )
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

NONPROD_EVIDENCE_HOST_ONLY = True
LOOPBACK_ONLY = True
PRINCIPAL_SOURCE = "nonprod_composition_test_account"
OWNER_SCOPE_SOURCE = "server_session_identity_allowlist"
REQUEST_BODY_IS_AUTHORITY = False
CANONICAL_MINT_REUSED_NOT_REIMPLEMENTED = True
PRODUCTION_PAIRING_STORE_ADDED = False
PRODUCTION_MUTATION = False
