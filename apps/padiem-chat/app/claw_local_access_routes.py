"""#3094 — the one real typed source behind the Web "Connect this computer" panel.

``GET /api/claw/local-access?conversationId=...`` returns exactly the narrow
shape ``static/claw-local-handoff.js`` (#3084) consumes, built from canonical
server device state through the single translation in
``app.claw_local_projection`` (G4). Nothing else in B62 may feed that panel.

Authority boundary
------------------
* Read-only and owner-scoped. Identity is the canonical session only; no session
  means 401 before any source call, and this route mutates nothing: no pairing
  challenge, no device binding, no device session, no task, no approval, no
  command, no execution.
* The device lifecycle is not re-declared or re-derived here. The injected truth
  source reports one canonical ``kagent.local_agent_pairing.DeviceLifecycle``
  value and this route only renames it through G4, so no second device-state
  authority and no new lifecycle state can appear.
* The handoff value stays opaque. It is forwarded verbatim when an upstream
  authority (#3080) produced one and omitted when it did not; nothing here
  mints, decodes, rewrites or re-encodes one, and the Web component that finally
  opens it is #3094's guarded adapter, not this file.
* An unconfigured source is not hidden as an error: the response stays 200 and
  says ``available: false`` with a bounded reason plus no usable device, so the
  panel cannot show a connection the server cannot justify.
* The response is assembled field-by-field from a closed allowlist, so raw
  command material, argv, environment, credentials, tokens, stderr and stack
  traces cannot reach the browser even if a source carries them.

Contract markers
----------------
``PAIRING_MINTING_AUTHORITY = "NO"``
``DEVICE_SESSION_AUTHORITY = "NO"``
``DEVICE_STATE_SOURCE = "canonical:kagent.local_agent_pairing.DeviceLifecycle"``
``DEVICE_STATE_TRANSLATION_AUTHORITY = "app.claw_local_projection"``
``NEW_LIFECYCLE_STATE_CREATED = 0``
``LOCAL_COMMAND_AUTHORITY = "NO"``
``HANDOFF_VALUE_MINTED_HERE = False``
``MUTATION = False``
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .claw_local_projection import (
    WEB_HANDOFF_CONTRACT_VERSION,
    handoff_projection,
    translate_device_lifecycle,
)

__all__ = [
    "CLAW_LOCAL_ACCESS_PATH",
    "CLAW_LOCAL_ACCESS_PROJECTION_VERSION",
    "LOCAL_ACCESS_UNCONFIGURED_REASON",
    "ClawLocalAccessTruthSource",
    "UnconfiguredClawLocalAccessTruthSource",
    "claw_local_access",
]

CLAW_LOCAL_ACCESS_PATH = "/api/claw/local-access"

# Version of the server projection envelope itself, distinct from the #3084 Web
# panel contract version it carries inside.
CLAW_LOCAL_ACCESS_PROJECTION_VERSION = "claw-local-access-projection/1"

LOCAL_ACCESS_UNCONFIGURED_REASON = "local_access_truth_source_unconfigured"

_MAX_CONVERSATION_ID_LENGTH = 128
_CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")

_MAX_REQUIRED_CAPABILITIES = 16

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

# Bounded reason vocabulary. An unexpected source failure is reported as one of
# these codes, never as the exception text.
_REASON_UNCONFIGURED = "local_access_truth_source_unconfigured"
_REASON_NO_OWNER = "owner_session_required"
_REASON_SOURCE_FAILED = "local_access_source_failed"
_REASON_OK = None


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _read(source: Any, key: str) -> Any:
    """Read one field from a mapping-or-dataclass source result, or ``None``."""

    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _flag(value: Any) -> bool:
    return value is True


def _text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:maximum] if len(trimmed) > maximum else trimmed


def _capabilities(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    cleaned: list[str] = []
    for item in value[:_MAX_REQUIRED_CAPABILITIES]:
        capability = _text(item, 60)
        if capability and capability not in cleaned:
            cleaned.append(capability)
    return cleaned


def _unavailable_projection(reason: str, conversation_id: str | None) -> dict[str, Any]:
    """A projection that asserts nothing beyond "we cannot confirm a device"."""

    return {
        "contractVersion": WEB_HANDOFF_CONTRACT_VERSION,
        "conversationId": conversation_id,
        "runId": None,
        "taskId": None,
        "requiresLocalAccess": False,
        "requiredCapabilities": [],
        "desktopInstalled": False,
        # No device claim at all: the Web module normalises an absent device to
        # ACTION_REQUIRED and not usable, which is the honest answer here.
        "device": None,
        "handoff": handoff_projection(value=None),
    }


def _validate_conversation_id(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > _MAX_CONVERSATION_ID_LENGTH:
        return None
    if not _CONVERSATION_ID_PATTERN.match(candidate):
        return None
    return candidate


class ClawLocalAccessTruthSource(Protocol):
    """The single typed source of device truth for the Web handoff panel.

    A source reports, for one owner and one conversation, the canonical device
    lifecycle value plus the already-decided presentation facts. Reading broker or
    binding state belongs to the source; this route never reaches into a broker,
    database or durable store itself.
    """

    async def project_local_access(
        self,
        *,
        owner_id: str,
        conversation_id: str,
        now: datetime,
    ) -> Any:  # pragma: no cover - protocol declaration
        ...


class UnconfiguredClawLocalAccessTruthSource:
    """Fail-closed default: no truth source wired, so nothing is usable.

    #3080 owns the pairing / broker authority that fills this in. Until that
    composition exists the panel is told honestly that no projection is available,
    which renders as "not connected, nothing to proceed with" rather than a
    fixture or a guess.
    """

    configured = False

    async def project_local_access(
        self,
        *,
        owner_id: str,
        conversation_id: str,
        now: datetime,
    ) -> Any:
        return {"configured": False, "reason": _REASON_UNCONFIGURED}


def _failure(reason: str, conversation_id: str | None) -> JSONResponse:
    """A 200 response that still asserts no device, so nothing can look usable."""

    return JSONResponse(
        {
            "ok": True,
            "available": False,
            "projectionVersion": CLAW_LOCAL_ACCESS_PROJECTION_VERSION,
            "reason": reason,
            "projection": _unavailable_projection(reason, conversation_id),
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_local_access(request: Request) -> JSONResponse:
    """Project canonical server device state into Web lifecycle vocabulary.

    Owner-scoped, read-only, no-store. This is the only real source for the #3084
    panel and the only thing #3094's Web adapter is allowed to read.
    """

    conversation_id = _validate_conversation_id(request.query_params.get("conversationId"))
    if conversation_id is None:
        return _error(400, "invalid_conversation_id", "conversationId가 올바르지 않습니다.")

    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return _error(401, _REASON_NO_OWNER, "인증이 필요합니다.")

    source = getattr(request.app.state, "claw_local_access_source", None)
    project = getattr(source, "project_local_access", None)
    if project is None or getattr(source, "configured", True) is False:
        return _failure(LOCAL_ACCESS_UNCONFIGURED_REASON, conversation_id)

    try:
        projected = project(
            owner_id=uid,
            conversation_id=conversation_id,
            now=datetime.now(timezone.utc),
        )
        if inspect.isawaitable(projected):
            projected = await projected
    except Exception:
        # Exception text can carry identifiers or storage detail, so only the
        # bounded code is reported.
        return _failure(_REASON_SOURCE_FAILED, conversation_id)

    if projected is None:
        return _failure(_REASON_SOURCE_FAILED, conversation_id)

    return JSONResponse(
        {
            "ok": True,
            "available": True,
            "projectionVersion": CLAW_LOCAL_ACCESS_PROJECTION_VERSION,
            "reason": _REASON_OK,
            "projection": {
                "contractVersion": WEB_HANDOFF_CONTRACT_VERSION,
                "conversationId": conversation_id,
                "runId": _read(projected, "run_id"),
                "taskId": _read(projected, "task_id"),
                "requiresLocalAccess": _flag(_read(projected, "requires_local_access")),
                "requiredCapabilities": _capabilities(_read(projected, "required_capabilities")),
                "desktopInstalled": _flag(_read(projected, "desktop_installed")),
                "device": translate_device_lifecycle(
                    _read(projected, "canonical_state"),
                    device_name=_read(projected, "device_name"),
                    platform=_read(projected, "platform"),
                ),
                "handoff": handoff_projection(
                    value=_read(projected, "handoff_value"),
                    conversation_id=_read(projected, "handoff_conversation_id")
                    or conversation_id,
                ),
            },
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

PAIRING_MINTING_AUTHORITY = "NO"
DEVICE_SESSION_AUTHORITY = "NO"
DEVICE_STATE_SOURCE = "canonical:kagent.local_agent_pairing.DeviceLifecycle"
DEVICE_STATE_TRANSLATION_AUTHORITY = "app.claw_local_projection"
NEW_LIFECYCLE_STATE_CREATED = 0
LOCAL_COMMAND_AUTHORITY = "NO"
HANDOFF_VALUE_MINTED_HERE = False
MUTATION = False
PRODUCTION_MUTATION = False
LOCAL_VALIDATION_STATUS = "PENDING"

