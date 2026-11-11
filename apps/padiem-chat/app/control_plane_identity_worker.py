from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import inspect
import os
import re
import time
from typing import Any

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.tenants import (
    CanonicalTenant,
    CanonicalTenantState,
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    IdentityLinkState,
    ProductIdentityLink,
    SubjectType,
)

from .control_plane_identity import IdentityBridgeError
from .request_telemetry import current_request_id, is_safe_request_id
from .request_timing import timed_async


_MAX_RPC_TICKET_CHARS = 24_576
_LINK_KEYS = frozenset({"product_id", "product_user_id", "canonical_subject_id", "state"})
# #3247: the reverse product-user lookup returns exactly the linked product user
# id and nothing else — no subject, no state, no provider material.
_SESSION_KEYS_LEGACY = frozenset(
    {"session_id", "product_id", "subject", "issued_at", "expires_at", "state", "revision"}
)
_SESSION_KEYS_TENANT = _SESSION_KEYS_LEGACY | {"tenant_id"}
# #5441: the revoke-all answer carries the count and the revoked sessions. The
# count is the authoritative statement; the session list is the readable
# projection of the same rows.
_REVOKE_ALL_KEYS = frozenset({"ok", "revoked_count", "sessions"})
_SUBJECT_KEYS = frozenset({"subject_type", "subject_id"})
_TICKET_KEYS = frozenset({"connect_ticket", "connector_id", "expires_at"})
_CONNECTOR_WORKSPACE_KEYS_ABSENT = frozenset({"present"})
_CONNECTOR_WORKSPACE_KEYS_PRESENT = frozenset({"present", "workspace_ref"})
_CONNECTOR_CONTEXT_KEYS_ABSENT = frozenset({"present"})
_CONNECTOR_CONTEXT_KEYS_PRESENT = frozenset(
    {"present", "product_id", "subject_id", "actor_ref", "workspace_ref"}
)
_TENANT_KEYS = frozenset({"tenant_id", "state", "created_at"})
_MEMBERSHIP_KEYS_LEGACY = frozenset({"tenant_id", "canonical_subject_id", "state", "created_at"})
_MEMBERSHIP_KEYS = _MEMBERSHIP_KEYS_LEGACY | {"role"}
_MEMBERSHIP_RESOLVE_KEYS = frozenset(
    {"tenant_id", "canonical_subject_id", "state", "created_at", "role"}
)
_REVIEWED_CONNECTORS = frozenset({
    "gmail", "google-drive", "google-calendar", "b66-google-drive-file", "b66-google-drive-full",
})
B66_GOOGLE_DRIVE_FILE_CONNECTOR = "b66-google-drive-file"
B66_GOOGLE_DRIVE_FULL_CONNECTOR = "b66-google-drive-full"
_CONNECTOR_CONSENT_RPC_KEYS = frozenset({
    "consent_id", "device_id", "granted_at", "withdrawn_at",
    "dispatch_authorized", "grants_read", "grants_write",
})
_CONNECTOR_SCHEMA_RPC_KEYS = frozenset({"schema", "installed_by_default"})
_CONNECTOR_CONSENT_CONFIRMATION_VERSION = "pc-enrollment-consent-v1"
_CONNECTOR_CURRENT_CONSENT_KEYS = frozenset({
    "consent_id", "device_id", "owner_subject_id", "account_ref", "workspace_ref",
    "granted_at", "withdrawn_at",
})
_CONNECTOR_CHALLENGE_SESSION_BINDING_KEYS = frozenset({
    "challenge_id", "session_id_bound", "expires_at", "raw_session_id_returned",
})
_CONNECTOR_REDEEM_AUTHORIZATION_KEYS = frozenset({
    "challenge_id", "consent_id", "device_id", "owner_subject_id", "account_ref",
    "workspace_ref", "authorized_at", "dispatch_authorized", "grants_read", "grants_write",
})


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        converted = dict(value)
    except (TypeError, ValueError):
        return None
    return converted


def _closed(value: Any, keys: frozenset[str], field_name: str) -> dict[str, Any]:
    wire = _dict(value)
    if wire is None or set(wire) != keys:
        raise IdentityBridgeError(
            503,
            "control_plane_rpc_invalid",
            f"{field_name} returned invalid canonical data.",
        )
    return wire


def _closed_session(value: Any) -> dict[str, Any]:
    """Accept only the legacy or canonical tenant-aware auth-session schema.

    #2176 deliberately made tenant_id additive and omitted it when unavailable.
    B62 must therefore accept exactly the legacy seven-key shape or the
    tenant-aware eight-key shape, while continuing to reject arbitrary RPC
    expansion and client-invented tenancy fields.
    """

    wire = _dict(value)
    if wire is None or set(wire) not in {_SESSION_KEYS_LEGACY, _SESSION_KEYS_TENANT}:
        raise IdentityBridgeError(
            503,
            "control_plane_rpc_invalid",
            "auth session returned invalid canonical data.",
        )
    return wire


def _time(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise IdentityBridgeError(503, "control_plane_rpc_invalid", f"{field_name} is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IdentityBridgeError(503, "control_plane_rpc_invalid", f"{field_name} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IdentityBridgeError(503, "control_plane_rpc_invalid", f"{field_name} is invalid.")
    return parsed


def _status_for_code(code: str) -> int:
    if code in {
        "inactive_auth_session",
        "canonical_auth_session_not_found",
        "canonical_product_identity_link_not_found",
        "canonical_product_identity_link_not_active",
    }:
        return 401
    if code in {
        "connector_context_session_mismatch",
        "identity_authority_product_mismatch",
        "unreviewed_connect_scope",
    }:
        return 403
    return 503


@dataclass(frozen=True, slots=True)
class PrivateGoogleConnectTicket:
    connect_ticket: str = field(repr=False)
    connector_id: str = ""
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.connect_ticket, str)
            or not self.connect_ticket
            or len(self.connect_ticket) > _MAX_RPC_TICKET_CHARS
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector ticket is invalid.")
        if self.connector_id not in _REVIEWED_CONNECTORS:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector ticket is invalid.")
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector ticket expiry is invalid.")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "expires_at": self.expires_at.isoformat(),
            "raw_connect_ticket": False,
        }


#: #6919: one identity RPC slower than this leaves a journal line naming the
#: method and the milliseconds. On 2026-11-05 the ``identity`` bucket of a PC
#: read's /api/mcp request ran 0.35-6.9 s with nothing in the journal to say
#: which of the calls behind it was slow. 0 journals every call.
IDENTITY_SLOW_RPC_MS_ENV = "PADIEM_CHAT_IDENTITY_SLOW_MS"
IDENTITY_SLOW_RPC_MS_DEFAULT = 250
_SAFE_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _identity_slow_rpc_ms() -> int:
    raw = os.environ.get(IDENTITY_SLOW_RPC_MS_ENV, "")
    try:
        value = int(str(raw).strip()) if str(raw).strip() else IDENTITY_SLOW_RPC_MS_DEFAULT
    except ValueError:
        return IDENTITY_SLOW_RPC_MS_DEFAULT
    return min(60_000, max(0, value))


def journal_identity_rpc(method_name: str, elapsed_ms: float, outcome: str) -> None:
    """One bounded line per slow identity RPC: method, milliseconds, outcome.

    Only fixed identifiers travel - the RPC method name, a code from the
    closed error set or ``ok``, and the request id - never the payload or a
    response value. Written with ``print`` like ``sqlite_slow_execute`` so it
    reaches the host journal, whose INFO loggers are not captured.
    """
    if elapsed_ms < _identity_slow_rpc_ms():
        return
    method = method_name if _SAFE_LABEL.fullmatch(str(method_name)) else "other"
    code = outcome if _SAFE_LABEL.fullmatch(str(outcome)) else "other"
    request_id = current_request_id()
    if not is_safe_request_id(request_id):
        request_id = "none"
    print("identity_rpc_slow method=%s ms=%d outcome=%s request_id=%s"
          % (method, int(round(elapsed_ms)), code, request_id), flush=True)


# 261106 · subject→product_user 역방향 조회 프로세스 캐시(짧은 TTL).
# /internal/chat/engine-pc-files 같은 서버 소유 경로가 같은 canonical subject 를
# 요청마다 다시 조회한다(11-03 이후 느린 이벤트 133건 전수가 이 경로, p50 441ms).
# 링크는 resolve_or_create_product_link 이 유일하게 만들고 remove_product_link 가
# 유일하게 지우므로, 두 메서드가 성공하면 같은 키를 무효화한다. 키에 product_id 와
# canonical_subject_id 가 모두 들어가 다른 사용자·다른 제품 결과가 섞이지 않는다.
PRODUCT_USER_CACHE_TTL_SECONDS = 60.0
PRODUCT_USER_CACHE_MAX_ENTRIES = 1024
_product_user_cache: dict[tuple[str, str], tuple[float, str]] = {}


def _product_user_cache_get(product_id: str, canonical_subject_id: str) -> str | None:
    from .identity_cache_metrics import record
    entry = _product_user_cache.get((product_id, canonical_subject_id))
    if entry is None:
        record('subject', 'resolve_product_user_for_subject', False)
        return None
    stored_at, product_user_id = entry
    if (time.monotonic() - stored_at) >= PRODUCT_USER_CACHE_TTL_SECONDS:
        _product_user_cache.pop((product_id, canonical_subject_id), None)
        record('subject', 'resolve_product_user_for_subject', False)
        return None
    record('subject', 'resolve_product_user_for_subject', True)
    return product_user_id


def _product_user_cache_put(product_id: str, canonical_subject_id: str, product_user_id: str) -> None:
    if len(_product_user_cache) >= PRODUCT_USER_CACHE_MAX_ENTRIES:
        oldest = next(iter(_product_user_cache), None)
        if oldest is not None:
            _product_user_cache.pop(oldest, None)
    _product_user_cache[(product_id, canonical_subject_id)] = (time.monotonic(), product_user_id)


def _product_user_cache_invalidate(product_id: str, canonical_subject_id: str) -> None:
    _product_user_cache.pop((product_id, canonical_subject_id), None)


class CloudflareControlPlaneIdentityAuthority:
    """B62 adapter over the private Control Plane identity Worker Service Binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("Control Plane identity Service Binding is required")
        self._binding = binding

    @timed_async('identity')
    async def _rpc_envelope(self, method_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Validated ``{"ok": true, ...}`` envelope from one identity RPC.

        Kept separate from the dict success-field projection because the
        reverse product-user lookup answers with a scalar ``product_user_id``
        rather than a nested object (#5015). #6919: a slow call is journaled
        by method name (see ``journal_identity_rpc``).
        """
        started = time.perf_counter()
        outcome = "ok"
        try:
            return await self._rpc_envelope_unmeasured(method_name, payload)
        except IdentityBridgeError as exc:
            outcome = str(getattr(exc, "code", "error") or "error")
            raise
        finally:
            journal_identity_rpc(method_name, (time.perf_counter() - started) * 1000.0, outcome)

    async def _rpc_envelope_unmeasured(self, method_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        method = getattr(self._binding, method_name, None)
        if not callable(method):
            raise IdentityBridgeError(
                503,
                "control_plane_identity_unavailable",
                "Canonical identity service is unavailable.",
            )
        try:
            result = _dict(await _maybe_await(method(payload)))
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "control_plane_identity_unavailable",
                "Canonical identity service is unavailable.",
            ) from exc
        if result is None or not isinstance(result.get("ok"), bool):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        if result["ok"] is False:
            if set(result) != {"ok", "error"}:
                raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
            error = _dict(result.get("error"))
            if error is None or set(error) != {"code", "message"} or not isinstance(error.get("code"), str):
                raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
            code = error["code"]
            raise IdentityBridgeError(
                _status_for_code(code),
                code,
                "Canonical identity request was rejected.",
            )
        return result

    async def _rpc(self, method_name: str, payload: dict[str, Any], success_field: str) -> dict[str, Any]:
        result = await self._rpc_envelope(method_name, payload)
        if set(result) != {"ok", success_field}:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        payload_wire = _dict(result.get(success_field))
        if payload_wire is None:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        return payload_wire

    async def resolve_or_create_product_link(
        self,
        *,
        product_id: str,
        product_user_id: str,
        auth_provider: str,
        provider_subject: str,
    ) -> ProductIdentityLink:
        wire = _closed(
            await self._rpc(
                "resolve_or_create_product_link",
                {
                    "product_id": product_id,
                    "product_user_id": product_user_id,
                    "auth_provider": auth_provider,
                    "provider_subject": provider_subject,
                },
                "link",
            ),
            _LINK_KEYS,
            "identity link",
        )
        try:
            # 261106 · a create/rebind changes the reverse lookup for this
            # exact pair; drop the stale cache entry before returning.
            _product_user_cache_invalidate(wire["product_id"], wire["canonical_subject_id"])
            return ProductIdentityLink(
                product_id=wire["product_id"],
                product_user_id=wire["product_user_id"],
                canonical_subject_id=wire["canonical_subject_id"],
                state=IdentityLinkState(wire["state"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity link is invalid.") from exc

    async def establish_auth_session(
        self,
        *,
        product_id: str,
        subject: CanonicalSubjectRef,
        authenticated_at: datetime,
        not_after: datetime,
    ) -> AuthSessionSnapshot:
        wire = _closed_session(
            await self._rpc(
                "establish_auth_session",
                {
                    "product_id": product_id,
                    "subject": subject.to_public_dict(),
                    "authenticated_at": authenticated_at.isoformat(),
                    "not_after": not_after.isoformat(),
                },
                "session",
            )
        )
        return self._session_from_wire(wire)

    async def resolve_auth_session(self, *, session_id: str) -> AuthSessionSnapshot:
        wire = _closed_session(
            await self._rpc("resolve_auth_session", {"session_id": session_id}, "session")
        )
        return self._session_from_wire(wire)

    async def revoke_auth_session(self, *, product_id: str, session_id: str) -> AuthSessionSnapshot:
        """Revoke exactly one canonical auth session in the Control Plane (#5225).

        The canonical session store is the single revocation authority. The
        caller names the product and the one session id; the private authority
        resolves the row, checks the product scope, and materializes the
        canonical terminal REVOKE transition itself. No other session of the
        same subject is affected.
        """

        if not isinstance(product_id, str) or not product_id:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        if not isinstance(session_id, str) or not session_id:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        wire = _closed_session(
            await self._rpc(
                "revoke_auth_session",
                {"product_id": product_id, "session_id": session_id},
                "session",
            )
        )
        return self._session_from_wire(wire)

    async def revoke_all_auth_sessions(
        self, *, product_id: str, product_user_id: str
    ) -> list[AuthSessionSnapshot]:
        """Revoke every canonical auth session of one product user (#5441).

        A replaced credential has to end every session it could still
        authenticate, on every device. The canonical session store is the only
        revocation authority, so this call names only the product and the
        product user: the private authority resolves the canonical subject and
        the session rows itself and materializes the terminal REVOKE
        transition on each one.
        """

        if not isinstance(product_id, str) or not product_id:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        if not isinstance(product_user_id, str) or not product_user_id:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        wire = _closed(
            await self._rpc_envelope(
                "revoke_all_auth_sessions",
                {"product_id": product_id, "product_user_id": product_user_id},
            ),
            _REVOKE_ALL_KEYS,
            "revoke-all sessions",
        )
        raw_sessions = wire.get("sessions")
        if not isinstance(raw_sessions, list):
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        return [self._session_from_wire(_closed_session(item)) for item in raw_sessions]

    async def resolve_current_auth_session(
        self, *, product_id: str, product_user_id: str
    ) -> AuthSessionSnapshot:
        """#3243 read-only current ACTIVE session for one product user.

        Server-derived: the RPC names only the product and the product user, so
        the caller can never supply a ``session_id``, ``subject_id``,
        ``tenant_id``, ``provider`` or a clock. The private authority resolves
        the canonical subject and the newest effective session itself.
        """

        if not isinstance(product_id, str) or not product_id:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        if not isinstance(product_user_id, str) or not product_user_id:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "Canonical session is unavailable."
            )
        wire = _closed_session(
            await self._rpc(
                "resolve_current_auth_session",
                {"product_id": product_id, "product_user_id": product_user_id},
                "session",
            )
        )
        return self._session_from_wire(wire)

    async def resolve_product_user_for_subject(
        self, *, product_id: str, canonical_subject_id: str
    ) -> str:
        """#3247 read-only reverse lookup: canonical subject -> B62 product user.

        Server-derived: the RPC names only the product and the canonical
        subject, so the caller can never supply a ``product_user_id``, a
        provider, a provider subject or an ``owner_ref``. The private
        authority requires exactly one ACTIVE link for the exact
        ``(product_id, canonical_subject_id)`` pair and fails closed on a
        missing, inactive, ambiguous or corrupt one. No link is ever created
        here.
        """

        if not isinstance(product_id, str) or not product_id:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        if not isinstance(canonical_subject_id, str) or not canonical_subject_id:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        # 261106 · the short-TTL process cache answers the repeated reverse
        # lookup for the same subject without one DO RPC per request. The link
        # writers below invalidate the same key, so a rebind or a removal is
        # visible immediately inside this process; a mutation made in another
        # process stays bounded by the TTL.
        cached = _product_user_cache_get(product_id, canonical_subject_id)
        if cached is not None:
            return cached
        result = await self._rpc_envelope(
            "resolve_product_user_for_subject",
            {"product_id": product_id, "canonical_subject_id": canonical_subject_id},
        )
        # The Control Plane answers this read-only reverse lookup with the
        # scalar ``product_user_id`` next to ``ok`` (#3247/#5015).
        if set(result) != {"ok", "product_user_id"}:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        product_user_id = result.get("product_user_id")
        if not isinstance(product_user_id, str) or not product_user_id:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity link is invalid.")
        _product_user_cache_put(product_id, canonical_subject_id, product_user_id)
        return product_user_id

    async def list_active_product_links_for_subject(
        self, *, canonical_subject_id: str
    ) -> list[dict[str, str]]:
        if not isinstance(canonical_subject_id, str) or not canonical_subject_id:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        result = await self._rpc_envelope(
            "list_active_product_links_for_subject",
            {"canonical_subject_id": canonical_subject_id},
        )
        if set(result) != {"ok", "links"} or not isinstance(result.get("links"), list):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        links: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw in result["links"]:
            item = _dict(raw)
            if item is None or set(item) != {"product_id", "product_user_id", "state"}:
                raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
            product_id = item.get("product_id")
            product_user_id = item.get("product_user_id")
            state = item.get("state")
            if not all(isinstance(value, str) and value for value in (product_id, product_user_id)) or state != "active":
                raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
            pair = (product_id, product_user_id)
            if pair in seen:
                raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
            seen.add(pair)
            links.append({"product_id": product_id, "product_user_id": product_user_id, "state": state})
        return links

    async def remove_product_link(
        self, *, product_id: str, product_user_id: str, canonical_subject_id: str,
        account_deletion_operation_id: str | None = None,
    ) -> dict[str, Any]:
        if not all(isinstance(value, str) and value for value in (product_id, product_user_id, canonical_subject_id)):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        result = await self._rpc_envelope(
            "remove_product_link",
            {
                "product_id": product_id,
                "product_user_id": product_user_id,
                "canonical_subject_id": canonical_subject_id,
                "account_deletion_operation_id": account_deletion_operation_id,
            },
        )
        keys = {"ok", "removed", "remaining_links", "common_account_deleted", "revoked_sessions", "already_deleted"}
        if set(result) != keys:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        if (
            not isinstance(result.get("removed"), bool)
            or not isinstance(result.get("common_account_deleted"), bool)
            or not isinstance(result.get("already_deleted"), bool)
            or isinstance(result.get("remaining_links"), bool)
            or not isinstance(result.get("remaining_links"), int)
            or result["remaining_links"] < 0
            or isinstance(result.get("revoked_sessions"), bool)
            or not isinstance(result.get("revoked_sessions"), int)
            or result["revoked_sessions"] < 0
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")
        # 261106 · the removal invalidates the reverse lookup for this pair.
        _product_user_cache_invalidate(product_id, canonical_subject_id)
        return {key: result[key] for key in keys if key != "ok"}

    async def resolve_connector_owner_scope(self, *, session_id: str) -> dict[str, str]:
        """Identity verified scope; no account or workspace supplied by Claw."""
        if not isinstance(session_id, str) or not session_id:
            raise IdentityBridgeError(401, "canonical_auth_session_not_found", "Canonical session unavailable.")
        scope = _dict(
            await self._rpc("resolve_connector_owner_scope", {"session_id": session_id}, "scope")
        )
        # 2026-11-04: the authority answers with the session owner's own
        # canonical subject id beside the established two keys (the usr_… axis
        # the ownership maps key on). Require those two, accept the additive
        # key, and keep every other shape invalid.
        if (
            scope is None
            or not {"account_ref", "workspace_ref"} <= set(scope)
            or not set(scope) <= {"account_ref", "workspace_ref", "owner_subject_id"}
            or any(not isinstance(value, str) or not value for value in scope.values())
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical connector scope invalid.")
        return scope

    async def resolve_connector_workspace(self, *, session_id: str) -> str | None:
        """#2830 B-1A read: canonical workspace_ref for one existing session.

        Payload is closed to ``session_id`` and no workspace may be asserted by
        the caller. ``None`` means the session is valid but no canonical
        connector workspace has been minted yet; that is an absence, not a
        connector state, and it carries no B62 status projection.
        """

        if not isinstance(session_id, str) or not session_id:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "Canonical session is unavailable."
            )
        # ``_rpc`` already validates the ok/error envelope and returns the
        # unwrapped ``workspace`` payload, or raises on any malformed shape.
        workspace = await self._rpc(
            "resolve_connector_workspace", {"session_id": session_id}, "workspace"
        )
        present = workspace.get("present")
        if not isinstance(present, bool):
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        if present is False:
            # workspace_ref is absent by contract when present=False.
            if set(workspace) != _CONNECTOR_WORKSPACE_KEYS_ABSENT:
                raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
            return None
        if set(workspace) != _CONNECTOR_WORKSPACE_KEYS_PRESENT:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        workspace_ref = workspace.get("workspace_ref")
        if not isinstance(workspace_ref, str) or not workspace_ref:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        return workspace_ref

    async def resolve_connector_context(self, *, session_id: str) -> dict[str, str] | None:
        """Read one canonical session's own actor/workspace/subject context.

        The payload is closed to ``session_id``. This RPC is only usable by a
        trusted server host; it never accepts caller-supplied actor, account,
        workspace, subject, tenant or product identity. ``None`` means the
        canonical connector context has not been minted yet and host connector
        work must fail closed.
        """

        if not isinstance(session_id, str) or not session_id:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "Canonical session is unavailable."
            )
        context = await self._rpc(
            "resolve_connector_context", {"session_id": session_id}, "context"
        )
        present = context.get("present")
        if not isinstance(present, bool):
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        if present is False:
            if set(context) != _CONNECTOR_CONTEXT_KEYS_ABSENT:
                raise IdentityBridgeError(
                    503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
                )
            return None
        if set(context) != _CONNECTOR_CONTEXT_KEYS_PRESENT:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
            )
        for key in ("product_id", "subject_id", "actor_ref", "workspace_ref"):
            value = context.get(key)
            if not isinstance(value, str) or not value:
                raise IdentityBridgeError(
                    503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data."
                )
        return context

    async def resolve_active_memberships(
        self,
        *,
        canonical_subject_id: str,
    ) -> tuple[str, ...]:
        method = getattr(self._binding, "resolve_active_memberships", None)
        if not callable(method):
            raise IdentityBridgeError(
                503,
                "control_plane_identity_unavailable",
                "Canonical tenant authority is unavailable.",
            )
        try:
            result = _dict(
                await _maybe_await(
                    method({"canonical_subject_id": canonical_subject_id})
                )
            )
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "control_plane_identity_unavailable",
                "Canonical tenant authority is unavailable.",
            ) from exc
        if result is None or set(result) != {"ok", "tenant_ids"} or result.get("ok") is not True:
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant authority returned invalid data.",
            )
        raw = result.get("tenant_ids")
        if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant authority returned invalid data.",
            )
        if len(set(raw)) != len(raw):
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant authority returned duplicate memberships.",
            )
        return tuple(raw)

    async def resolve_active_tenant_membership(
        self,
        *,
        tenant_id: str,
        canonical_subject_id: str,
        now: datetime,
    ) -> TenantMembership:
        wire = _closed(
            await self._rpc(
                "resolve_active_tenant_membership",
                {
                    "tenant_id": tenant_id,
                    "canonical_subject_id": canonical_subject_id,
                    "now": now.isoformat(),
                },
                "membership",
            ),
            _MEMBERSHIP_RESOLVE_KEYS,
            "canonical tenant membership",
        )
        try:
            membership = TenantMembership(
                tenant_id=wire["tenant_id"],
                canonical_subject_id=wire["canonical_subject_id"],
                state=TenantMembershipState(wire["state"]),
                created_at=_time(wire["created_at"], "membership created_at"),
                role=TenantMembershipRole(wire["role"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant membership is invalid.",
            ) from exc
        if (
            membership.tenant_id != tenant_id
            or membership.canonical_subject_id != canonical_subject_id
            or membership.state is not TenantMembershipState.ACTIVE
            or membership.role is None
        ):
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant membership is invalid.",
            )
        return membership

    async def create_tenant(self) -> str:
        wire = _closed(
            await self._rpc("create_tenant", {}, "tenant"),
            _TENANT_KEYS,
            "canonical tenant",
        )
        try:
            tenant = CanonicalTenant(
                tenant_id=wire["tenant_id"],
                state=CanonicalTenantState(wire["state"]),
                created_at=_time(wire["created_at"], "tenant created_at"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical tenant is invalid."
            ) from exc
        return tenant.tenant_id

    async def assign_tenant_membership(
        self,
        *,
        tenant_id: str,
        canonical_subject_id: str,
        role: str | None = None,
    ) -> TenantMembership:
        if role is not None and role != TenantMembershipRole.OWNER.value:
            raise ValueError("only the canonical OWNER role may be assigned here")
        wire = _dict(
            await self._rpc(
                "assign_tenant_membership",
                {
                    "tenant_id": tenant_id,
                    "canonical_subject_id": canonical_subject_id,
                    **({"role": role} if role is not None else {}),
                },
                "membership",
            )
        )
        if wire is None or set(wire) not in (_MEMBERSHIP_KEYS_LEGACY, _MEMBERSHIP_KEYS):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical tenant membership is invalid.")
        try:
            membership = TenantMembership(
                tenant_id=wire["tenant_id"],
                canonical_subject_id=wire["canonical_subject_id"],
                state=TenantMembershipState(wire["state"]),
                created_at=(
                    _time(wire["created_at"], "membership created_at")
                    if wire.get("created_at") is not None
                    else None
                ),
                role=TenantMembershipRole(wire["role"]) if wire.get("role") is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant membership is invalid.",
            ) from exc
        if (
            membership.tenant_id != tenant_id
            or membership.canonical_subject_id != canonical_subject_id
            or membership.state is not TenantMembershipState.ACTIVE
        ):
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant membership does not match the request.",
            )
        return membership

    async def ensure_personal_tenant_membership(
        self,
        *,
        canonical_subject_id: str,
        role: str | None = None,
    ) -> tuple[str, TenantMembership]:
        """Atomically resolve or create the subject's one personal tenant.

        The authority performs the membership read and the tenant/membership
        write in one transaction, so two concurrent first logins share one
        tenant instead of minting two.
        """
        if role is not None and role != TenantMembershipRole.OWNER.value:
            raise ValueError("only the canonical OWNER role may be assigned here")
        envelope = await self._rpc_envelope(
            "ensure_personal_tenant_membership",
            {
                "canonical_subject_id": canonical_subject_id,
                **({"role": role} if role is not None else {}),
            },
        )
        if set(envelope) != {"ok", "tenant", "membership"}:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical tenant membership is invalid."
            )
        tenant_wire = _closed(envelope["tenant"], _TENANT_KEYS, "canonical tenant")
        membership_wire = _closed(
            envelope["membership"], _MEMBERSHIP_KEYS, "canonical tenant membership"
        )
        try:
            tenant_id = tenant_wire["tenant_id"]
            membership = TenantMembership(
                tenant_id=membership_wire["tenant_id"],
                canonical_subject_id=membership_wire["canonical_subject_id"],
                state=TenantMembershipState(membership_wire["state"]),
                created_at=_time(membership_wire["created_at"], "membership created_at"),
                role=TenantMembershipRole(membership_wire["role"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(
                503, "control_plane_rpc_invalid", "Canonical tenant membership is invalid."
            ) from exc
        if (
            not isinstance(tenant_id, str)
            or not tenant_id
            or membership.tenant_id != tenant_id
            or membership.canonical_subject_id != canonical_subject_id
            or membership.state is not TenantMembershipState.ACTIVE
            or membership.role is None
        ):
            raise IdentityBridgeError(
                503,
                "control_plane_rpc_invalid",
                "Canonical tenant membership does not match the request.",
            )
        return tenant_id, membership

    async def install_connector_enrollment_schema(self, *, migration_id: str) -> dict[str, Any]:
        wire = _closed(
            await self._rpc(
                "install_connector_enrollment_schema",
                {"migration_id": migration_id},
                "schema",
            ),
            _CONNECTOR_SCHEMA_RPC_KEYS,
            "connector enrollment schema receipt",
        )
        if wire.get("schema") != migration_id or wire.get("installed_by_default") is not False:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector enrollment schema receipt is invalid.")
        return wire

    async def grant_connector_enrollment_consent(
        self, *, session_id: str, device_id: str, confirmed: bool,
        confirmation_version: str = _CONNECTOR_CONSENT_CONFIRMATION_VERSION,
    ) -> dict[str, Any]:
        if confirmed is not True or confirmation_version != _CONNECTOR_CONSENT_CONFIRMATION_VERSION:
            raise IdentityBridgeError(403, "connector_enrollment_explicit_consent_required", "Explicit owner consent is required.")
        wire = _closed(
            await self._rpc(
                "grant_connector_enrollment_consent",
                {"session_id": session_id, "device_id": device_id,
                 "confirmed": True, "confirmation_version": confirmation_version},
                "consent",
            ),
            _CONNECTOR_CONSENT_RPC_KEYS,
            "connector enrollment consent receipt",
        )
        if (
            wire.get("device_id") != device_id
            or not isinstance(wire.get("consent_id"), str)
            or not isinstance(wire.get("granted_at"), str)
            or wire.get("withdrawn_at") is not None
            or wire.get("dispatch_authorized") is not False
            or wire.get("grants_read") is not False
            or wire.get("grants_write") is not False
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector enrollment consent receipt is invalid.")
        _time(wire["granted_at"], "connector consent grant time")
        return wire

    async def revoke_connector_enrollment_consent(
        self, *, session_id: str, consent_id: str, confirmed: bool,
        confirmation_version: str = _CONNECTOR_CONSENT_CONFIRMATION_VERSION,
    ) -> dict[str, Any]:
        if confirmed is not True or confirmation_version != _CONNECTOR_CONSENT_CONFIRMATION_VERSION:
            raise IdentityBridgeError(403, "connector_enrollment_explicit_consent_required", "Explicit owner revocation is required.")
        wire = _closed(
            await self._rpc(
                "revoke_connector_enrollment_consent",
                {"session_id": session_id, "consent_id": consent_id,
                 "confirmed": True, "confirmation_version": confirmation_version},
                "consent",
            ),
            _CONNECTOR_CONSENT_RPC_KEYS,
            "connector enrollment revocation receipt",
        )
        if (
            wire.get("consent_id") != consent_id
            or not isinstance(wire.get("device_id"), str)
            or not isinstance(wire.get("granted_at"), str)
            or not isinstance(wire.get("withdrawn_at"), str)
            or wire.get("dispatch_authorized") is not False
            or wire.get("grants_read") is not False
            or wire.get("grants_write") is not False
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector enrollment revocation receipt is invalid.")
        _time(wire["granted_at"], "connector consent grant time")
        _time(wire["withdrawn_at"], "connector consent withdrawal time")
        return wire

    async def resolve_connector_enrollment_consent_for_device(
        self, *, session_id: str, device_id: str
    ) -> dict[str, Any]:
        wire = _closed(
            await self._rpc(
                "resolve_connector_enrollment_consent_for_device",
                {"session_id": session_id, "device_id": device_id},
                "consent",
            ),
            _CONNECTOR_CURRENT_CONSENT_KEYS,
            "current connector enrollment consent",
        )
        if (
            wire.get("device_id") != device_id
            or not all(isinstance(wire.get(k), str) and wire[k] for k in (
                "consent_id", "owner_subject_id", "account_ref", "workspace_ref", "granted_at"
            ))
            or wire.get("withdrawn_at") is not None
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Current connector consent is invalid.")
        _time(wire["granted_at"], "connector consent grant time")
        return wire

    async def bind_connector_enrollment_challenge(
        self, *, session_id: str, challenge_id: str, expires_at: str
    ) -> dict[str, Any]:
        wire = _closed(
            await self._rpc(
                "bind_connector_enrollment_challenge",
                {"session_id": session_id, "challenge_id": challenge_id, "expires_at": expires_at},
                "binding",
            ),
            _CONNECTOR_CHALLENGE_SESSION_BINDING_KEYS,
            "connector challenge session binding",
        )
        if (
            wire.get("challenge_id") != challenge_id
            or wire.get("session_id_bound") is not True
            or wire.get("raw_session_id_returned") is not False
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector challenge session binding is invalid.")
        _time(wire["expires_at"], "connector challenge expiry")
        return wire

    async def authorize_connector_enrollment_redeem(
        self, *, challenge_id: str, consent_id: str, device_id: str,
        owner_ref: str, account_ref: str, workspace_ref: str,
    ) -> dict[str, Any]:
        request = {
            "challenge_id": challenge_id, "consent_id": consent_id, "device_id": device_id,
            "owner_ref": owner_ref, "account_ref": account_ref, "workspace_ref": workspace_ref,
        }
        wire = _closed(
            await self._rpc(
                "authorize_connector_enrollment_redeem", request, "authorization"
            ),
            _CONNECTOR_REDEEM_AUTHORIZATION_KEYS,
            "connector enrollment redemption authorization",
        )
        expected = {
            "challenge_id": challenge_id, "consent_id": consent_id, "device_id": device_id,
            "owner_subject_id": owner_ref, "account_ref": account_ref, "workspace_ref": workspace_ref,
        }
        if (
            any(wire.get(k) != value for k, value in expected.items())
            or wire.get("dispatch_authorized") is not False
            or wire.get("grants_read") is not False
            or wire.get("grants_write") is not False
        ):
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Connector enrollment authorization is invalid.")
        _time(wire["authorized_at"], "connector redemption authorization time")
        return wire

    async def issue_google_connect_ticket(
        self,
        *,
        session_id: str,
        connector_id: str,
    ) -> PrivateGoogleConnectTicket:
        wire = _closed(
            await self._rpc(
                "issue_google_connect_ticket",
                {"session_id": session_id, "connector_id": connector_id},
                "ticket",
            ),
            _TICKET_KEYS,
            "Google connect ticket",
        )
        return PrivateGoogleConnectTicket(
            connect_ticket=wire["connect_ticket"],
            connector_id=wire["connector_id"],
            expires_at=_time(wire["expires_at"], "connect ticket expiry"),
        )

    async def issue_b66_google_drive_file_connect_ticket(
        self, *, session_id: str
    ) -> PrivateGoogleConnectTicket:
        """Issue only the reviewed B66 Drive-file connect ticket for one session.

        The connector is fixed in code, so a browser can never select the
        shared ``google-drive`` readonly connector, another connector, or a
        Google write scope of its choice.
        """

        return await self.issue_google_connect_ticket(
            session_id=session_id,
            connector_id=B66_GOOGLE_DRIVE_FILE_CONNECTOR,
        )

    async def issue_b66_google_drive_full_connect_ticket(
        self, *, session_id: str
    ) -> PrivateGoogleConnectTicket:
        """Issue only the reviewed B66 full-Drive ticket for one session.

        The connector is fixed in code, so a browser can never select the
        shared ``google-drive`` connector, another connector, or a Google scope
        of its choice. A prior ``drive.file`` grant is not reinterpreted.
        """

        return await self.issue_google_connect_ticket(
            session_id=session_id,
            connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        )

    @staticmethod
    def _session_from_wire(wire: dict[str, Any]) -> AuthSessionSnapshot:
        subject_wire = _closed(wire.get("subject"), _SUBJECT_KEYS, "canonical subject")
        try:
            return AuthSessionSnapshot(
                session_id=wire["session_id"],
                product_id=wire["product_id"],
                subject=CanonicalSubjectRef(
                    subject_type=SubjectType(subject_wire["subject_type"]),
                    subject_id=subject_wire["subject_id"],
                ),
                issued_at=_time(wire["issued_at"], "issued_at"),
                expires_at=_time(wire["expires_at"], "expires_at"),
                state=AuthSessionState(wire["state"]),
                revision=wire["revision"],
                tenant_id=wire.get("tenant_id"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical auth session is invalid.") from exc


CONTROL_PLANE_IDENTITY_SERVICE_BINDING_ADAPTER = True
BROWSER_CANONICAL_ID_AUTHORITY = False
CLIENT_ACCOUNT_WORKSPACE_AUTHORITY = False
RAW_CONNECT_TICKET_LOGGED = False
PRODUCTION_IDENTITY_BINDING = False
CLIENT_IDENTITY_AUTHORITY = False
