"""#2830 Phase A backend-only connector status projection (B62 chat).

Two truths are published from strictly separate axes and are never merged:

1. PLATFORM SUPPORT TRUTH — which READ capabilities the shared platform
   supports today. Canonical contract facts are read from the existing
   network-free Core capability snapshots in ``packages/padiem-ai-core``
   (reused, never copied or reimplemented).
2. WORKSPACE CONNECTED/AUTHORIZED TRUTH — whether a specific workspace is
   actually connected. B62 currently has NO trusted per-user
   workspace-state authority (no Engine grant D1 wiring, no Control Plane
   OAuth storage access), so every row reports
   ``workspace_state="unverified"`` with ``workspace_reason=
   "no_trusted_b62_workspace_state_projection"``. The projection never
   guesses ``connected`` and never guesses ``disconnected``.

The response is a bounded projection: no secret, no raw account/provider
identifier, no credential binding, no OAuth payload, no authorization URL,
no provider/Core scope material, no SEND/WRITE tool identity. SEND/WRITE
is simply not projected as authority anywhere.

Zero runtime reads: no provider call, no OAuth call, no session lookup,
no D1 lookup, no workspace identity lookup.
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

PROJECTION_VERSION = "b62-connector-status-projection.v1"

WORKSPACE_STATE_UNVERIFIED = "unverified"
WORKSPACE_REASON_NO_TRUSTED_AUTHORITY = "no_trusted_b62_workspace_state_projection"

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


async def connectors_status(request: Request) -> JSONResponse:
    """Public read-only GET; response carries no user- or workspace-specific data."""

    del request
    return JSONResponse(build_connector_status_projection(), headers=dict(_NO_STORE_HEADERS))
