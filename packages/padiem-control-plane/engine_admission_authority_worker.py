"""Private Service Binding gateway for canonical Engine E7 admission authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from workers import DurableObject, Response, WorkerEntrypoint

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.engine_admission_authority import (
    CloudflareEngineAdmissionAuthorityStore,
    canonical_subject_from_wire,
    reservation_scope_from_wire,
    snapshot_from_wire,
)
from padiem_control_plane.engine_entitlement_producer import (
    ensure_authenticated_user_engine_entitlement,
)

_AUTHORITY_REF = "control-plane.engine-admission.production.v1"
_ALLOWED_PRODUCTS: frozenset[str] = frozenset(
    {"b62", "b54-padiem-claw"}
)
_FETCH_KEYS = frozenset({"product_id", "subject"})
_RESERVE_KEYS = frozenset({"reservation"})
_RECORD_KEYS = frozenset({"usage_event"})
_INSTALL_KEYS = frozenset({"snapshot"})


def _closed(
    payload: Any,
    keys: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or frozenset(payload) != keys:
        raise ControlPlaneContractError(
            "invalid_engine_admission_authority_rpc",
            f"{label} must contain exactly the reviewed fields",
        )
    return dict(payload)


def _safe_error(
    exc: ControlPlaneContractError,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": exc.code,
            "message": "Control Plane Engine admission request was rejected",
        },
    }


class CanonicalEngineAdmissionDurableObject(DurableObject):
    """Canonical entitlement + usage authority. No public HTTP route exists."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        raw_products = getattr(
            env,
            "CONTROL_PLANE_ALLOWED_PRODUCTS",
            None,
        )
        parsed = frozenset(
            part.strip()
            for part in str(raw_products or "").split(",")
            if part.strip()
        )
        if parsed != _ALLOWED_PRODUCTS:
            raise RuntimeError(
                "Engine admission authority product boundary does not "
                "match the reviewed product set"
            )
        self._store = CloudflareEngineAdmissionAuthorityStore(
            ctx.storage,
            allowed_product_ids=_ALLOWED_PRODUCTS,
        )

        identity = getattr(env, "CONTROL_PLANE_IDENTITY", None)
        if (
            identity is None
            or not callable(
                getattr(identity, "resolve_product_user_for_subject", None)
            )
            or not callable(
                getattr(identity, "resolve_current_auth_session", None)
            )
        ):
            raise RuntimeError(
                "required CONTROL_PLANE_IDENTITY private service binding is missing"
            )
        self._identity = identity

    async def _ensure_current_entitlement(
        self,
        *,
        product_id: str,
        subject: Any,
        now: datetime,
    ):
        subject_ref = canonical_subject_from_wire(subject)
        return await ensure_authenticated_user_engine_entitlement(
            self._store,
            self._identity,
            product_id=product_id,
            subject=subject_ref,
            now=now,
        )

    async def fetch_entitlement_snapshot(
        self,
        payload: dict,
    ) -> dict:
        try:
            wire = _closed(
                payload,
                _FETCH_KEYS,
                "entitlement fetch RPC",
            )
            now = datetime.now(UTC)
            snapshot = await self._ensure_current_entitlement(
                product_id=wire["product_id"],
                subject=wire["subject"],
                now=now,
            )
            return {
                "ok": True,
                "snapshot": snapshot.to_policy_dict(),
            }
        except ControlPlaneContractError as exc:
            return _safe_error(exc)

    async def reserve_usage(
        self,
        payload: dict,
    ) -> dict:
        try:
            wire = _closed(
                payload,
                _RESERVE_KEYS,
                "usage reservation RPC",
            )
            now = datetime.now(UTC)
            product_id, subject = reservation_scope_from_wire(
                wire["reservation"]
            )
            await ensure_authenticated_user_engine_entitlement(
                self._store,
                self._identity,
                product_id=product_id,
                subject=subject,
                now=now,
            )
            reservation = self._store.reserve_usage(
                wire["reservation"],
                now=now,
            )
            return {
                "ok": True,
                "reservation": reservation,
            }
        except ControlPlaneContractError as exc:
            return _safe_error(exc)

    async def record_usage(
        self,
        payload: dict,
    ) -> dict:
        try:
            wire = _closed(
                payload,
                _RECORD_KEYS,
                "usage record RPC",
            )
            receipt = self._store.record_usage(
                wire["usage_event"],
                now=datetime.now(UTC),
            )
            return {
                "ok": True,
                "receipt": receipt,
            }
        except ControlPlaneContractError as exc:
            return _safe_error(exc)

    async def install_entitlement_snapshot(
        self,
        payload: dict,
    ) -> dict:
        """Internal CP producer seam; not forwarded by the Engine gateway."""

        try:
            wire = _closed(
                payload,
                _INSTALL_KEYS,
                "entitlement install RPC",
            )
            snapshot = snapshot_from_wire(
                wire["snapshot"]
            )
            stored = self._store.install_entitlement_snapshot(
                snapshot,
                now=datetime.now(UTC),
            )
            return {
                "ok": True,
                "snapshot": stored.to_policy_dict(),
            }
        except ControlPlaneContractError as exc:
            return _safe_error(exc)

    async def fetch(self, request):
        del request
        return Response(
            "Not Found",
            status=404,
            headers={"cache-control": "no-store"},
        )


class Default(WorkerEntrypoint):
    """Engine-facing private gateway: read/reserve/record only."""

    def _stub(self):
        namespace = self.env.CONTROL_PLANE_ENGINE_ADMISSION
        object_id = namespace.idFromName(_AUTHORITY_REF)
        return namespace.get(object_id)

    async def fetch_entitlement_snapshot(
        self,
        payload: dict,
    ) -> dict:
        return await self._stub().fetch_entitlement_snapshot(
            payload
        )

    async def reserve_usage(
        self,
        payload: dict,
    ) -> dict:
        return await self._stub().reserve_usage(
            payload
        )

    async def record_usage(
        self,
        payload: dict,
    ) -> dict:
        return await self._stub().record_usage(
            payload
        )

    async def fetch(self, request):
        del request
        return Response(
            "Not Found",
            status=404,
            headers={"cache-control": "no-store"},
        )


CANONICAL_ENGINE_ADMISSION_AUTHORITY_WORKER_SOURCE = True
PRIVATE_SERVICE_BINDING_RPC = True
PUBLIC_ROUTE_CONFIGURED = False
ENGINE_GATEWAY_CAN_INSTALL_ENTITLEMENTS = False
CONTROL_PLANE_IDENTITY_REQUIRED_FOR_ENTITLEMENT = True
PRODUCT_BILLING_LEDGER = False
PROVIDER_AUTHORITY_CHANGED = False
