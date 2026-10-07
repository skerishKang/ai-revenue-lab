"""#2830 Phase A / B-1C backend connector status projection (B62 chat).

Two truths are published from strictly separate axes and are never merged:

1. PLATFORM SUPPORT TRUTH — which READ capabilities the shared platform
   supports today. Canonical contract facts are read from the existing
   network-free Core capability snapshots in ``packages/padiem-ai-core``
   (reused, never copied or reimplemented).
2. WORKSPACE CONNECTED/AUTHORIZED TRUTH — whether a specific workspace is
   actually connected.

For the workspace axis this module is the *projection* only; it never becomes a
workspace authority. It has exactly two sources:

* **No trusted canonical session** (anonymous, or a signed-in session whose
  canonical identity/workspace cannot be resolved). Every row reports
  ``workspace_state="unverified"`` with a closed ``workspace_reason``. The
  projection never guesses ``connected`` and never guesses ``not_connected``;
  a row is only ever ``not_connected`` when a trusted authority said so
  explicitly.
* **Trusted canonical session** (B-1C). B62 **product authentication is proven
  first** (``auth_ready`` + a live product profile), and only then is the signed
  B62 product session resolved through the existing Control Plane identity
  shadow to a canonical ``auth_session_id``; the existing B-1B private
  composition (``compose_workspace_connector_truth``) yields bounded
  Gmail / Drive / Calendar truth. Only ``workspace_state`` and
  ``workspace_reason`` are updated from it — the private rows are never
  published verbatim.

A signed cookie is never sufficient on its own. ``COOKIE_UID_PRESENT !=
PRODUCT_USER_AUTHENTICATED``: a stale or deleted product user degrades to the
anonymous Phase-A projection and reaches no canonical private authority at all.

The reviewed workspace-truth scope is Gmail, Google Drive and Google Calendar,
mapped through an explicit closed table to the Core canonical connector ids.
Calendar uses the dedicated identity-free private Calendar presence RPC; the
default Gmail/Drive RPC is not widened. Telegram and Slack keep ``unverified``
because no trusted workspace authority exists for them here.

``workspace_state_authority`` is ``True`` only when canonical truth actually
participated in this response, i.e. at least one reviewed row was updated from a
trusted authority. It does **not** mean "every connector has workspace
authority" — each row's own ``workspace_state`` is the final truth source.

The response is a bounded projection: no secret, no raw account/provider
identifier, no credential binding, no OAuth payload, no authorization URL,
no provider/Core scope material, no SEND/WRITE tool identity. SEND/WRITE is
simply not projected as authority anywhere. Reading connector truth never
promotes to SEND/WRITE authority.

No provider call, no OAuth call, no D1 lookup and no workspace identity lookup
happens on the anonymous path; the only private reads on the authenticated path
are the two existing Control Plane Service Binding RPCs reached through the
already-wired ``app.state`` authorities.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_ai_core.calendar_capability import (
    CALENDAR_CONNECTOR_ID,
    calendar_capability_snapshot,
)
from padiem_ai_core.connectors import GMAIL_CONNECTOR_ID
from padiem_ai_core.drive_capability import DRIVE_CONNECTOR_ID, drive_capability_snapshot
from padiem_ai_core.gmail_capability import gmail_capability_snapshot
from padiem_ai_core.slack_capability import SLACK_CONNECTOR_ID, slack_capability_snapshot
from padiem_ai_core.telegram_capability import (
    TELEGRAM_CONNECTOR_ID,
    telegram_capability_snapshot,
)

from .auth_routes import auth_ready, current_user_id
from .connector_workspace_truth import (
    REVIEWED_WORKSPACE_TRUTH_CONNECTORS,
    compose_workspace_connector_truth,
)
from .control_plane_identity import IdentityBridgeError

PROJECTION_VERSION = "b62-connector-status-projection.v1"

WORKSPACE_STATE_UNVERIFIED = "unverified"
WORKSPACE_STATE_CONNECTED = "connected"
WORKSPACE_STATE_NOT_CONNECTED = "not_connected"
WORKSPACE_STATE_AMBIGUOUS = "ambiguous"

# Closed reason vocabulary for the workspace axis. A reason is only ever emitted
# when the state is ``unverified`` (the authority could not be trusted) or
# ``ambiguous`` (the authority was trusted and said the state is ambiguous).
WORKSPACE_REASON_NO_TRUSTED_AUTHORITY = "no_trusted_b62_workspace_state_projection"
WORKSPACE_REASON_IDENTITY_NOT_LINKED = "canonical_identity_not_linked"
WORKSPACE_REASON_NO_CANONICAL_WORKSPACE = "canonical_connector_workspace_not_resolved"
WORKSPACE_REASON_TRUTH_UNAVAILABLE = "canonical_workspace_truth_unavailable"
WORKSPACE_REASON_SESSION_NOT_FOUND = "canonical_workspace_session_not_found"
WORKSPACE_REASON_SESSION_INACTIVE = "canonical_workspace_session_inactive"
WORKSPACE_REASON_SESSION_MISMATCH = "canonical_workspace_session_mismatch"
WORKSPACE_REASON_SESSION_REFERENCE_INVALID = "canonical_workspace_session_reference_invalid"
WORKSPACE_REASON_IDENTITY_SERVICE_UNAVAILABLE = "canonical_identity_service_unavailable"
WORKSPACE_REASON_IDENTITY_RPC_INVALID = "canonical_identity_rpc_invalid"
WORKSPACE_REASON_IDENTITY_STORAGE_UNAVAILABLE = "canonical_identity_storage_unavailable"
WORKSPACE_REASON_CONNECTOR_CONTEXT_STORAGE_UNAVAILABLE = "canonical_connector_context_storage_unavailable"
WORKSPACE_REASON_CONNECTOR_CONTEXT_INVALID = "canonical_connector_context_invalid"
WORKSPACE_REASON_CONNECTOR_CONTEXT_PRODUCT_MISMATCH = "canonical_connector_context_wrong_product"
WORKSPACE_REASON_IDENTITY_UNCLASSIFIED_FAILURE = "canonical_identity_unclassified_failure"
WORKSPACE_REASON_CONNECTOR_NOT_REPORTED = "canonical_workspace_connector_not_reported"
WORKSPACE_REASON_AMBIGUOUS = "canonical_workspace_connector_ambiguous"

# Reviewed Control Plane identity failures that are safe to project as a bounded
# classification. The public API never echoes the upstream code/message and
# never projects any session/workspace/reference value. Unknown errors, and all
# Google OAuth/provider failures, remain the existing generic unavailable reason.
_IDENTITY_ERROR_TO_WORKSPACE_REASON = {
    "identity_workspace_session_not_found": WORKSPACE_REASON_SESSION_NOT_FOUND,
    "identity_workspace_session_inactive": WORKSPACE_REASON_SESSION_INACTIVE,
    "identity_workspace_session_mismatch": WORKSPACE_REASON_SESSION_MISMATCH,
    "identity_workspace_session_reference_invalid": WORKSPACE_REASON_SESSION_REFERENCE_INVALID,
    "identity_workspace_service_unavailable": WORKSPACE_REASON_IDENTITY_SERVICE_UNAVAILABLE,
    "identity_workspace_rpc_invalid": WORKSPACE_REASON_IDENTITY_RPC_INVALID,
    "identity_workspace_storage_unavailable": WORKSPACE_REASON_IDENTITY_STORAGE_UNAVAILABLE,
    "identity_workspace_context_storage_unavailable": WORKSPACE_REASON_CONNECTOR_CONTEXT_STORAGE_UNAVAILABLE,
    "identity_workspace_context_invalid": WORKSPACE_REASON_CONNECTOR_CONTEXT_INVALID,
    "identity_workspace_context_product_mismatch": WORKSPACE_REASON_CONNECTOR_CONTEXT_PRODUCT_MISMATCH,
    "identity_workspace_unclassified": WORKSPACE_REASON_IDENTITY_UNCLASSIFIED_FAILURE,
}

# Explicit closed mapping. Reviewed B-1B internal connector id ->
# (projection row name, public canonical connector id). This is a table, never a
# string heuristic, so no connector can drift into the workspace axis by name
# similarity. ``_require_reviewed_targets`` re-checks it against both the B-1B
# reviewed scope and the Core canonical ids on every authenticated read.
_WORKSPACE_TRUTH_TARGETS = {
    "gmail": ("gmail", GMAIL_CONNECTOR_ID),
    "google-drive": ("drive", DRIVE_CONNECTOR_ID),
    "google-calendar": ("calendar", CALENDAR_CONNECTOR_ID),
}

# Trusted B-1B state -> published (workspace_state, workspace_reason). The B-1B
# ``usable`` / ``expires_present`` / ``ambiguous`` fields are deliberately not
# projected: the public row shape stays exactly what Phase A published.
_B1B_STATE_TO_PUBLIC = {
    "connected": (WORKSPACE_STATE_CONNECTED, None),
    "not_connected": (WORKSPACE_STATE_NOT_CONNECTED, None),
    "ambiguous": (WORKSPACE_STATE_AMBIGUOUS, WORKSPACE_REASON_AMBIGUOUS),
}

# Canonical connector identifiers come from Core unchanged.
_CONNECTOR_IDS = {
    "drive": DRIVE_CONNECTOR_ID,
    "gmail": GMAIL_CONNECTOR_ID,
    "telegram": TELEGRAM_CONNECTOR_ID,
    "slack": SLACK_CONNECTOR_ID,
    "calendar": CALENDAR_CONNECTOR_ID,
}

# Accepted platform facts (#2830 issue body). The Core snapshot remains the
# contract authority; this table only states the approved READ availability.
_READ_AVAILABILITY = {
    "drive": ("complete", None),
    "gmail": ("complete", None),
    "telegram": ("complete", None),
    "slack": ("deferred", "slack_live_deferred"),
    "calendar": ("source_ready", "calendar_source_ready_live_deferred"),
}

_CONNECTOR_ORDER = ("drive", "gmail", "telegram", "slack", "calendar")

_ROW_KEYS = (
    "connector_id",
    "contract_version",
    "supported",
    "read_availability",
    "workspace_state",
    "workspace_reason",
    "deferred_reason",
)


def _core_snapshots() -> dict[str, dict[str, Any]]:
    return {
        "drive": drive_capability_snapshot(),
        "gmail": gmail_capability_snapshot(),
        "telegram": telegram_capability_snapshot(),
        "slack": slack_capability_snapshot(),
        "calendar": calendar_capability_snapshot(),
    }


def _require_read_contract(name: str, snapshot: dict[str, Any]) -> None:
    """Fail closed if Core no longer declares the promoted READ contract."""

    capabilities = snapshot.get("capabilities")
    if not isinstance(capabilities, dict) or "read" not in capabilities:
        raise RuntimeError(f"core snapshot '{name}' lost its READ contract")
    read_contract = capabilities["read"]
    if not isinstance(read_contract, dict):
        raise RuntimeError(f"core snapshot '{name}' READ contract is malformed")
    if not snapshot.get("read_tool_ids"):
        raise RuntimeError(f"core snapshot '{name}' declares no READ tools")


def _row(name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    _require_read_contract(name, snapshot)
    contract_version = snapshot.get("contract_version")
    if not isinstance(contract_version, str) or not contract_version:
        raise RuntimeError(f"core snapshot '{name}' has no contract version")
    read_availability, deferred_reason = _READ_AVAILABILITY[name]
    connector_id = _CONNECTOR_IDS[name]
    canonical_id = snapshot.get("connector_id")
    if isinstance(canonical_id, str) and canonical_id != connector_id:
        raise RuntimeError(f"core snapshot '{name}' connector id drifted")
    return {
        "connector_id": connector_id,
        "contract_version": contract_version,
        "supported": ["read"],
        "read_availability": read_availability,
        "workspace_state": WORKSPACE_STATE_UNVERIFIED,
        "workspace_reason": WORKSPACE_REASON_NO_TRUSTED_AUTHORITY,
        "deferred_reason": deferred_reason,
    }


def build_connector_status_projection() -> dict[str, Any]:
    """Deterministic projection of the two separated truth axes."""

    snapshots = _core_snapshots()
    rows = [_row(name, snapshots[name]) for name in _CONNECTOR_ORDER]
    return {
        "projection_version": PROJECTION_VERSION,
        "static_support_vs_workspace_state_separated": True,
        "send_write_authorized": False,
        "workspace_state_authority": False,
        "connectors": rows,
    }


_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

# Governance pins asserted by the contract tests.
NEW_WORKSPACE_AUTHORITY = False
NEW_IDENTITY_AUTHORITY = False
NEW_OAUTH_AUTHORITY = False
NEW_AUTHENTICATION_AUTHORITY = False
CLIENT_WORKSPACE_ASSERTION = False
IDENTITY_REF_PROJECTED = False
TOKEN_OR_SECRET_PROJECTED = False
SCOPE_PROJECTED = False
READ_TRUTH_PROMOTES_TO_SEND_WRITE = False
# Persisted Calendar READ grant state: read-only projection of the Engine's
# existing grant store. Chat keeps no grant store of its own and this surface
# can never activate, revoke, or write a grant.
SECOND_CALENDAR_GRANT_STORE = False
CALENDAR_READ_GRANT_STATE_WRITE_AUTHORITY = False
# B62 product authentication boundary. The canonical shadow is reached only
# after the local product session is proven against the product authority.
AUTH_READY_REQUIRED = True
PRODUCT_PROFILE_REQUIRED = True
SIGNED_COOKIE_ALONE_AUTHORIZES = False
SHADOW_PRESENCE_AUTHENTICATES_USER = False
CANONICAL_SESSION_REPLACES_PRODUCT_AUTH = False


def _require_reviewed_targets() -> None:
    """Fail closed if the closed mapping drifts from B-1B or Core."""

    for internal_id, (row_name, public_id) in _WORKSPACE_TRUTH_TARGETS.items():
        if internal_id not in REVIEWED_WORKSPACE_TRUTH_CONNECTORS:
            raise RuntimeError(f"workspace truth target '{internal_id}' is not reviewed")
        if row_name not in _CONNECTOR_IDS:
            raise RuntimeError(f"workspace truth row '{row_name}' is not projected")
        if _CONNECTOR_IDS[row_name] != public_id:
            raise RuntimeError(f"workspace truth target '{internal_id}' connector id drifted")


def _composed_overrides(connectors: Any) -> dict[str, tuple[str, str | None]] | None:
    """Map a B-1B connector list onto published row overrides.

    ``None`` means the composition envelope is malformed and must fail closed.
    Rows outside the reviewed scope are ignored rather than published. The
    reviewed-state vocabulary is enforced here as well, so a substituted
    authority cannot introduce an unknown state.
    """

    if not isinstance(connectors, (tuple, list)):
        return None
    overrides: dict[str, tuple[str, str | None]] = {}
    for row in connectors:
        if not isinstance(row, dict):
            return None
        internal_id = row.get("connector_id")
        if internal_id not in _WORKSPACE_TRUTH_TARGETS:
            continue
        published = _B1B_STATE_TO_PUBLIC.get(row.get("state"))
        if published is None:
            return None
        row_name = _WORKSPACE_TRUTH_TARGETS[internal_id][0]
        overrides[row_name] = published
    return overrides


async def _reviewed_workspace_truth(
    request: Request,
) -> tuple[dict[str, tuple[str, str | None]], str, bool, str | None]:
    """Compose reviewed workspace truth for the signed-in B62 product user.

    Returns ``(overrides, fallback_reason, authority, session_id)``:

    * ``overrides`` — published ``(workspace_state, workspace_reason)`` per
      reviewed row that a trusted authority spoke for;
    * ``fallback_reason`` — the closed reason for reviewed rows without an
      override;
    * ``authority`` — ``True`` only when canonical truth actually participated;
    * ``session_id`` — the canonical shadow session id once product
      authentication and the shadow proven, else ``None``. The persisted
      Calendar READ grant projection reuses this one resolution so the
      product profile and shadow are read exactly once per request.

    This never raises. Every failure is mapped to a closed, bounded reason, so
    an operational fault (missing binding, malformed RPC, unresolved session)
    can never be projected as ``not_connected``.

    B62 **product authentication is proven first**, using the same product
    authority the rest of the app uses — ``auth_ready`` plus a live product
    profile from the history store — before any canonical private authority is
    reached. A signed cookie is only a *candidate* identity:

        COOKIE_UID_PRESENT != PRODUCT_USER_AUTHENTICATED

    The canonical identity shadow is not a product authentication authority
    (``SHADOW_PRESENCE_AUTHENTICATES_USER=NO``) and a canonical auth session is
    not a substitute for the local B62 product session
    (``CANONICAL_SESSION_REPLACES_PRODUCT_AUTH=NO``). When product auth is not
    ready, absent, or cannot be evaluated, no private call is made at all.
    """

    # The canonical shadow session, once product authentication and the shadow
    # both prove out. Returned to the caller so the persisted Calendar READ
    # grant projection reuses the single profile/shadow read below.
    shadow_session_id: str | None = None

    # 1. Prove B62 product authentication before reaching any canonical private
    #    authority. A stale or deleted product user must never be able to read
    #    canonical workspace truth through the shadow.
    try:
        if not auth_ready(request):
            # auth_mode="off", or no product history store: not authenticated.
            return {}, WORKSPACE_REASON_NO_TRUSTED_AUTHORITY, False, None
        user_id = current_user_id(request)
        if user_id is None:
            # No valid signed product cookie.
            return {}, WORKSPACE_REASON_NO_TRUSTED_AUTHORITY, False, None
        history_store = getattr(request.app.state, "history_store", None)
        if history_store is None:
            return {}, WORKSPACE_REASON_NO_TRUSTED_AUTHORITY, False, None
        profile = await history_store.get_user(user_id)
    except Exception:  # noqa: BLE001 - product authentication could not be evaluated
        return {}, WORKSPACE_REASON_TRUTH_UNAVAILABLE, False, None
    if profile is None:
        # The cookie decodes to a uid that no longer has a product user. That is
        # the B62 "expired / not authenticated" state, so degrade exactly to the
        # anonymous Phase-A projection instead of reaching the canonical shadow.
        return {}, WORKSPACE_REASON_NO_TRUSTED_AUTHORITY, False, None

    # 2. Only now may the canonical private authorities be reached.
    try:
        _require_reviewed_targets()
    except RuntimeError:
        return {}, WORKSPACE_REASON_TRUTH_UNAVAILABLE, False, None

    identity_authority = getattr(request.app.state, "control_plane_identity_authority", None)
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    google_oauth_authority = getattr(request.app.state, "google_oauth_workspace_truth", None)
    if identity_authority is None or shadow_store is None or google_oauth_authority is None:
        return {}, WORKSPACE_REASON_TRUTH_UNAVAILABLE, False, None

    try:
        shadow = await shadow_store.load_projection(user_id)
    except Exception:  # noqa: BLE001 - a shadow read fault is never a workspace state
        return {}, WORKSPACE_REASON_TRUTH_UNAVAILABLE, False, None
    if shadow is None:
        return {}, WORKSPACE_REASON_IDENTITY_NOT_LINKED, False, None
    session_id = getattr(shadow, "auth_session_id", None)
    if not isinstance(session_id, str) or not session_id:
        return {}, WORKSPACE_REASON_IDENTITY_NOT_LINKED, False, None
    shadow_session_id = session_id

    try:
        result = await compose_workspace_connector_truth(
            identity_authority=identity_authority,
            google_oauth_authority=google_oauth_authority,
            session_id=session_id,
        )
    except IdentityBridgeError as exc:
        return (
            {},
            _IDENTITY_ERROR_TO_WORKSPACE_REASON.get(
                exc.code, WORKSPACE_REASON_TRUTH_UNAVAILABLE
            ),
            False,
            shadow_session_id,
        )
    except Exception:  # noqa: BLE001 - never leak a driver error into a state
        return {}, WORKSPACE_REASON_TRUTH_UNAVAILABLE, False, shadow_session_id

    if not isinstance(result, dict) or not isinstance(result.get("available"), bool):
        return {}, WORKSPACE_REASON_TRUTH_UNAVAILABLE, False, shadow_session_id
    if result["available"] is False:
        return {}, WORKSPACE_REASON_NO_CANONICAL_WORKSPACE, False, shadow_session_id

    overrides = _composed_overrides(result.get("connectors"))
    if overrides is None:
        return {}, WORKSPACE_REASON_TRUTH_UNAVAILABLE, False, shadow_session_id
    return overrides, WORKSPACE_REASON_CONNECTOR_NOT_REPORTED, bool(overrides), shadow_session_id


CALENDAR_READ_GRANT_ROW_FIELD = "calendar_read_grant_state"
CALENDAR_READ_GRANT_ACTIVE = "active"
CALENDAR_READ_GRANT_INACTIVE = "inactive"
CALENDAR_READ_GRANT_UNAVAILABLE = "unavailable"
_CALENDAR_ROW_CONNECTOR_ID = CALENDAR_CONNECTOR_ID


async def _reviewed_calendar_read_grant_state(
    request: Request,
    session_id: str | None,
) -> str | None:
    """Read-only persisted Calendar READ grant state for the signed-in user.

    ``session_id`` is the canonical shadow session the workspace-truth
    composition already proved (one product-profile/shadow read per request).
    The Engine is asked through the read-only state client (no write, no
    second authority) and only its closed answer travels:

    * ``active`` / ``inactive`` — the Engine's confirmed projection;
    * ``unavailable`` — the check ran but could not be trusted (transport,
      rejection, malformed body). It is never folded into ``inactive``;
    * ``None`` — this session may not be used to infer grant state at all
      (anonymous/untrusted, or the state client is unconfigured). The row
      then carries no grant field, exactly like the pre-feature shape.
    """

    if not isinstance(session_id, str) or not session_id:
        return None
    client = getattr(request.app.state, "calendar_read_state_engine_client", None)
    if client is None:
        return None
    try:
        state = await client.read_state(session_id=session_id)
    except Exception:  # noqa: BLE001 - a failed check is unavailable, never inactive
        return CALENDAR_READ_GRANT_UNAVAILABLE
    return state if state in (CALENDAR_READ_GRANT_ACTIVE, CALENDAR_READ_GRANT_INACTIVE) else (
        CALENDAR_READ_GRANT_UNAVAILABLE
    )


async def connectors_status(request: Request) -> JSONResponse:
    """Public read-only GET; adds canonical workspace truth when it is trusted.

    The platform support axis is always published unchanged. The workspace axis
    is only updated from a trusted canonical session; otherwise the Phase-A
    ``unverified`` rows are returned byte-for-byte.
    """

    document = build_connector_status_projection()
    overrides, fallback_reason, authority, session_id = await _reviewed_workspace_truth(request)
    if overrides or fallback_reason != WORKSPACE_REASON_NO_TRUSTED_AUTHORITY:
        rows = {row["connector_id"]: row for row in document["connectors"]}
        for row_name, public_id in _WORKSPACE_TRUTH_TARGETS.values():
            row = rows.get(public_id)
            if row is None:
                continue
            row["workspace_state"], row["workspace_reason"] = overrides.get(
                row_name, (WORKSPACE_STATE_UNVERIFIED, fallback_reason)
            )
        document["workspace_state_authority"] = authority
    # Additive third axis: the persisted Calendar READ grant, projected for the
    # calendar row only and only when a trusted canonical session allows the
    # question to be asked at all. The support and workspace axes above are
    # untouched; untrusted sessions get the pre-feature shape unchanged.
    grant_state = await _reviewed_calendar_read_grant_state(request, session_id)
    if grant_state is not None:
        for row in document["connectors"]:
            if row.get("connector_id") == _CALENDAR_ROW_CONNECTOR_ID:
                row[CALENDAR_READ_GRANT_ROW_FIELD] = grant_state
    return JSONResponse(document, headers=dict(_NO_STORE_HEADERS))
