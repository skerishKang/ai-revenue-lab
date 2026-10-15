"""Owner-approved, no-manual-code Connector delivery composition (#4139).

Source-only, NOT mounted on a production/acceptance HTTP route. The existing
canonical Identity consent and Broker challenge issuance remain authoritative.

The browser never receives a pairing code, credential or device execution
permission. A separate, preexisting PC-initiated authenticated rendezvous
must prove a live device request before this service can be instantiated.
The outbound channel may deliver exactly once; only the canonical Windows
WSS/DPAPI ACK and Broker state can later establish actual enrollment.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Protocol

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from .control_plane_identity import IdentityBridgeError

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PAIRING_CODE = re.compile(r"^[0-9a-f]{32}$")
_INTENT_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_CONFIRM_VERSION = "pc-enrollment-consent-v1"

# Intentionally not registered through app_factory or owner runtime mount.
ONE_CLICK_ENROLLMENT_HTTP_MOUNTED = False
ONE_CLICK_ENROLLMENT_PRODUCTION_ENABLED = False


class OneClickDenied(RuntimeError):
    """Bounded failure reason; no secret, raw upstream error or code."""


class ConfirmedPcRendezvous(Protocol):
    """Trusted outbound gateway, backed by an atomic one-use intent ledger.

    The port must atomically reserve ONE live, possession-verified offer in a
    durable per-request ledger BEFORE any canonical challenge is issued.
    Duplicate approvals must be refused, including concurrent requests.
    No implementation supplied by this module; never trust browser JSON.
    """
    async def reserve_once(self, *, request_ref: str) -> dict[str, Any]: ...
    async def deliver_once(
        self, *, request_ref: str, device_id: str,
        challenge_id: str, pairing_code: str,
    ) -> None: ...


class CanonicalConsentPort(Protocol):
    async def grant_connector_enrollment_consent(
        self, *, session_id: str, device_id: str,
        confirmed: bool, confirmation_version: str,
    ) -> dict[str, Any]: ...


class CanonicalIssuePort(Protocol):
    async def issue(
        self, *, canonical_session_id: str, device_id: str,
    ) -> dict[str, Any]: ...


def _ref(value: Any) -> bool:
    return type(value) is str and _SAFE_REF.fullmatch(value) is not None


class OneClickOwnerApproval:
    """One owner action, without exposing the one-use code to the browser.

    This is not an identity or enrollment authority. It composes trusted
    dependencies and returns only a 'delivery requested' indication.
    Any exception after canonical challenge issuance leaves a one-use
    challenge unconfirmed; NEVER silently retry it or claim registration.
    """

    def __init__(
        self, *, identity: CanonicalConsentPort,
        host: CanonicalIssuePort, pc_rendezvous: ConfirmedPcRendezvous,
    ) -> None:
        if any(not callable(getattr(target, method, None)) for target, method in (
            (identity, "grant_connector_enrollment_consent"),
            (host, "issue"),
            (pc_rendezvous, "reserve_once"),
            (pc_rendezvous, "deliver_once"),
        )):
            raise ValueError("canonical owner/PC authorities unavailable")
        self._identity = identity
        self._host = host
        self._pc = pc_rendezvous

    async def approve(
        self, *, owner_session: AuthSessionSnapshot,
        request_ref: str, confirmed: bool,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if (
            type(owner_session) is not AuthSessionSnapshot
            or owner_session.product_id != "b54-padiem-claw"
            or not owner_session.tenant_id
            or not owner_session.is_active(now=now)
            or not _ref(owner_session.session_id)
        ):
            raise OneClickDenied("canonical_owner_session_required")
        if confirmed is not True:
            raise OneClickDenied("explicit_pc_consent_required")
        if type(request_ref) is not str or _INTENT_REF.fullmatch(request_ref) is None:
            raise OneClickDenied("invalid_pending_pc_request")

        try:
            pending = await self._pc.reserve_once(request_ref=request_ref)
        except Exception:
            raise OneClickDenied("pending_pc_unavailable") from None
        if (
            type(pending) is not dict
            or set(pending) != {
                "request_ref", "device_id", "device_possession_verified",
                "connected_to_outbound_channel", "reserved_once", "expires_at",
            }
            or pending["request_ref"] != request_ref
            or pending["device_possession_verified"] is not True
            or pending["connected_to_outbound_channel"] is not True
            or pending["reserved_once"] is not True
            or not _ref(pending["device_id"])
        ):
            raise OneClickDenied("pending_pc_not_authenticated")
        try:
            expiry = datetime.fromisoformat(
                pending["expires_at"].replace("Z", "+00:00")
            )
            if (expiry.utcoffset() is None or expiry <= now
                    or expiry > now + timedelta(minutes=2)):
                raise ValueError("expired or unbounded lifetime")
        except (ValueError, AttributeError, TypeError, OverflowError) as exc:
            raise OneClickDenied("pending_pc_expired") from exc

        device_id = pending["device_id"]
        try:
            # Reuse the existing still-active canonical grant on this owner/PC.
            try:
                current = await self._identity.resolve_connector_enrollment_consent_for_device(
                    session_id=owner_session.session_id, device_id=device_id,
                )
            except IdentityBridgeError as exc:
                if getattr(exc, "code", None) != "enrollment_consent_required":
                    raise
                current = None
            reused = current is not None
            if reused:
                consent = current
            else:
                # Existing Identity confirmation-version contract is preserved
                # internally AFTER owner POST + live WSS possession were proved.
                consent = await self._identity.grant_connector_enrollment_consent(
                    session_id=owner_session.session_id,
                    device_id=device_id, confirmed=True,
                    confirmation_version=_CONFIRM_VERSION,
                )
        except Exception:
            raise OneClickDenied("canonical_consent_unavailable") from None
        if (
            type(consent) is not dict
            or consent.get("device_id") != device_id
            or not _ref(consent.get("consent_id"))
            or consent.get("withdrawn_at") is not None
            or (reused and consent.get("owner_subject_id") != owner_session.subject.subject_id)
            or (not reused and any(consent.get(field) is not False for field in (
                "dispatch_authorized", "grants_read", "grants_write",
            )))
        ):
            raise OneClickDenied("canonical_consent_unconfirmed")

        try:
            issued = await self._host.issue(
                canonical_session_id=owner_session.session_id,
                device_id=device_id,
            )
        except Exception:
            raise OneClickDenied("canonical_challenge_unavailable") from None
        if (
            type(issued) is not dict
            or set(issued) != {
                "challenge", "pairing_code", "code_returned_once",
                "raw_device_credential", "dispatch_authorized",
            }
            or type(issued["challenge"]) is not dict
            or not _ref(issued["challenge"].get("challenge_id"))
            or type(issued["pairing_code"]) is not str
            or _PAIRING_CODE.fullmatch(issued["pairing_code"]) is None
            or issued["code_returned_once"] is not True
            or issued["raw_device_credential"] is not False
            or issued["dispatch_authorized"] is not False
        ):
            raise OneClickDenied("canonical_challenge_invalid")
        try:
            await self._pc.deliver_once(
                request_ref=request_ref, device_id=device_id,
                challenge_id=issued["challenge"]["challenge_id"],
                pairing_code=issued["pairing_code"],
            )
        except Exception:
            # Challenge may have been issued; it must NOT be replayed.
            raise OneClickDenied("pc_delivery_unconfirmed") from None
        # Delivery acknowledgement is not Windows DPAPI installation proof.
        return {
            "ok": True, "state": "awaiting_device_confirmation",
            "device_id": device_id, "connected": False,
            "registered": False, "dispatch_authorized": False,
        }
