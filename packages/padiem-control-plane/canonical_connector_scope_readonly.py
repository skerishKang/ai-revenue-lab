"""#4139 read-only candidate for shared Connector scope in existing Identity DO.

B54 login carries canonical subject+tenant but the existing connector context
has historically been keyed by B62 product + canonical subject. This adapter
only READS that already-established subject's canonical connector account /
workspace. It NEVER mints a context, rewrites a tenant, derives a scope from
browser fields or treats an unreviewed workspace alias as authority.

This is an UNCOMPOSED source candidate. It must not be enabled unless security
review confirms that the existing B62 canonical_connector_context is the
single product-neutral owner of shared PC scope for B54/Claw, B66 and Engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentScope

LEGACY_CONTEXT_PRODUCT = "b62"
SCOPE_BRIDGE_WIRED = False
SHARED_SCOPE_AUTHORITY_APPROVED = False
PRODUCT_LOCAL_SCOPE_MINTED = False


class CanonicalMembershipReader(Protocol):
    def resolve_active_tenant_membership(
        self, *, tenant_id: str, canonical_subject_id: str, now: datetime
    ) -> Any: ...


def _rows(cursor: Any) -> list[dict[str, Any]]:
    """Normalize Durable Object / Pyodide JavaScript proxy rows.

    The same established row is a plain ``list``/``dict`` in a normal Durable
    Object run and an opaque proxy container with proxy rows in the deployed
    Worker, so an ``isinstance`` check alone reports a healthy single row as
    "not established". This reuses the canonical Identity authority's existing
    ``to_py()``/``dict()`` conversion order — exactly as the sibling
    ``canonical_connector_enrollment_durable._rows`` already does — while still
    refusing a malformed row rather than silently filling fields.
    """
    to_array = getattr(cursor, "toArray", None)
    if not callable(to_array):
        raise ControlPlaneContractError(
            "canonical_scope_unavailable", "canonical context lookup unavailable"
        )
    raw = to_array()
    output: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            output.append(dict(item))
            continue
        to_py = getattr(item, "to_py", None)
        converted = to_py() if callable(to_py) else None
        if isinstance(converted, dict):
            output.append(dict(converted))
            continue
        try:
            output.append(dict(item))
        except (TypeError, ValueError) as exc:
            raise ControlPlaneContractError(
                "canonical_scope_unavailable", "canonical context row is invalid"
            ) from exc
    return output


class ReadOnlyExistingConnectorScope:
    def __init__(self, *, identity_do_storage: Any, membership_authority: CanonicalMembershipReader):
        sql = getattr(identity_do_storage, "sql", None)
        if not callable(getattr(sql, "exec", None)):
            raise ValueError("existing Identity DO SQL required")
        if not callable(getattr(membership_authority, "resolve_active_tenant_membership", None)):
            raise ValueError("canonical tenant membership authority required")
        self._sql = sql
        self._membership = membership_authority

    def resolve_scope(
        self, *, subject_id: str, tenant_ref: str | None, now: datetime
    ) -> ConnectorEnrollmentScope:
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ControlPlaneContractError("canonical_scope_time_invalid", "server time required")
        if not isinstance(subject_id, str) or not subject_id or not isinstance(tenant_ref, str) or not tenant_ref:
            raise ControlPlaneContractError("canonical_scope_identity_required", "canonical subject and tenant required")
        # The existing canonical authority checks tenant existence, active
        # status, exact subject membership, and role. No caller alias allowed.
        self._membership.resolve_active_tenant_membership(
            tenant_id=tenant_ref, canonical_subject_id=subject_id, now=now.astimezone(timezone.utc)
        )
        try:
            rows = _rows(
                self._sql.exec(
                    "SELECT account_ref,workspace_ref FROM canonical_connector_context "
                    "WHERE product_id=? AND subject_id=?",
                    LEGACY_CONTEXT_PRODUCT, subject_id,
                )
            )
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise ControlPlaneContractError("canonical_scope_unavailable", "canonical context lookup unavailable") from exc
        # Exactly one established row is still required. Normalizing the row
        # shape must never widen the count, the product pin or the subject pin.
        if len(rows) != 1:
            raise ControlPlaneContractError("canonical_scope_not_established", "one established connector context required")
        try:
            return ConnectorEnrollmentScope(
                owner_subject_id=subject_id,
                account_ref=rows[0]["account_ref"],
                workspace_ref=rows[0]["workspace_ref"],
                product_scoped=False,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ControlPlaneContractError("canonical_scope_invalid", "canonical context result invalid") from exc
