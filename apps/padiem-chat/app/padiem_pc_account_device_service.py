"""#4139 private-only orchestration for a shared PADIEM My Devices read.

No public route or app_factory mount. The injected owner-scope resolver must
reuse the existing Identity DO and return its current canonical session,
live tenant OWNER membership, and reviewed product-neutral PC scope. Device
facts come only from the existing private canonical Broker Service Binding.
No product registration DB, new credential, new identity or ONLINE authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
from typing import Any, Protocol

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.local_agent_pc_access import ProductPcAccessPolicy
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentScope
from padiem_control_plane.padiem_pc_account_devices import (
    account_device_view, product_device_view_for_owner,
    verified_owner_scope,
)

PADIEM_PC_ACCOUNT_READ_ROUTE_MOUNTED = False
PADIEM_PC_ACCOUNT_DEFAULT_READ_ENABLED = False
PADIEM_PC_ACCOUNT_REVOKE_ROUTE_MOUNTED = False


@dataclass(frozen=True, slots=True)
class VerifiedPcOwnerContext:
    """Trusted Identity DO result; not a browser-supplied user identity."""

    session: AuthSessionSnapshot
    membership_role: object
    scope: ConnectorEnrollmentScope


class CanonicalOwnerPcContextPort(Protocol):
    async def resolve_current_owner_context(
        self, *, canonical_session_id: str
    ) -> VerifiedPcOwnerContext: ...


class CanonicalBrokerDirectoryPort(Protocol):
    async def device_directory(
        self, *, account_ref: str, workspace_ref: str
    ) -> dict[str, Any]: ...


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _refused() -> dict[str, Any]:
    return {
        "ok": False, "available": False, "reason": "pc_account_read_unavailable",
        "devices": [], "device_count": 0, "owner_scoped": False,
        "directory_verified": False, "online_decided_here": False,
        "dispatch_authorized": False, "grants_read": False,
        "grants_write": False,
    }


class PrivateCanonicalBrokerDirectoryReader:
    """Typed projection-only Service Binding reader, no public HTTP fallback."""

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("existing private canonical Broker Service Binding is required")
        self._binding = binding

    async def device_directory(
        self, *, account_ref: str, workspace_ref: str
    ) -> dict[str, Any]:
        rpc = getattr(self._binding, "device_directory", None)
        if not callable(rpc):
            raise RuntimeError("canonical Broker directory RPC unavailable")
        reply = await _await(rpc({
            "account_ref": account_ref, "workspace_ref": workspace_ref,
        }))
        if not isinstance(reply, dict):
            convert = getattr(reply, "to_py", None)
            reply = convert() if callable(convert) else None
        if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
            raise RuntimeError("invalid private canonical Broker directory envelope")
        # Never pass this unredacted value to a browser or support log.
        return reply


class PadiemPcAccountDeviceService:
    """Account-wide read and separately authorized product-scoped read.

    DEFAULT OFF; no create/update/revoke/dispatch operations are exposed.
    """

    def __init__(
        self, *, identity: CanonicalOwnerPcContextPort,
        broker: CanonicalBrokerDirectoryPort, read_enabled: bool = False,
    ) -> None:
        self._identity = identity
        self._broker = broker
        self._read_enabled = read_enabled is True

    async def _trusted_directory(self, session_id: str) -> tuple[
        VerifiedPcOwnerContext, dict[str, Any], datetime
    ] | None:
        if not self._read_enabled or not isinstance(session_id, str) or not session_id:
            return None
        now = datetime.now(timezone.utc)
        try:
            ctx = await _await(self._identity.resolve_current_owner_context(
                canonical_session_id=session_id,
            ))
            if (
                type(ctx) is not VerifiedPcOwnerContext
                or not verified_owner_scope(
                    session=ctx.session, membership_role=ctx.membership_role,
                    scope=ctx.scope, now=now,
                )
            ):
                return None
            directory = await _await(self._broker.device_directory(
                account_ref=ctx.scope.account_ref,
                workspace_ref=ctx.scope.workspace_ref,
            ))
            if not isinstance(directory, dict):
                return None
            return ctx, directory, now
        except Exception:
            # Fail closed: neither tenant/owner nor Broker exceptions may leak.
            return None

    async def list_account_devices(self, *, canonical_session_id: str) -> dict[str, Any]:
        resolved = await self._trusted_directory(canonical_session_id)
        if resolved is None:
            return _refused()
        context, directory, now = resolved
        return account_device_view(
            session=context.session, membership_role=context.membership_role,
            scope=context.scope, directory_result=directory, now=now,
        )

    async def list_product_devices(
        self, *, canonical_session_id: str, product_id: str,
        server_policy: ProductPcAccessPolicy,
    ) -> dict[str, Any]:
        if not isinstance(server_policy, ProductPcAccessPolicy):
            return _refused()
        resolved = await self._trusted_directory(canonical_session_id)
        if resolved is None:
            return _refused()
        context, directory, now = resolved
        return product_device_view_for_owner(
            session=context.session, membership_role=context.membership_role,
            scope=context.scope, directory_result=directory,
            policy=server_policy, product_id=product_id, now=now,
        )
