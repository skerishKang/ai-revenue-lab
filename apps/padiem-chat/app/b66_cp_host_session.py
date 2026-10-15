"""B66 #4089 Step 2-B3: signed Padiem session to CP owner / workspace proof.

This module is a typed, server-only composition port. It deliberately does not
activate an OAuth grant, mint a Google subject, or expose a public route. Host
production composition still fails closed by default; callers must prove and
inject the underlying server-trusted Padiem->CP link.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .b66_cp_drive_boundary import (
    B66VerifiedCPDriveOwnerLink,
    _REF_RE,
    _B66_USER_RE,
)

B66_CP_HOST_SESSION_PROVEN = False
B66_CP_HOST_AUTH_SESSION_GATE = "DEFAULT_DENY"
B66_CP_AUTH_SESSION_TO_CP = "IDENTIFIED_UNWIRED"
B66_CP_HOST_COMPOSITION_PROVEN = False
B66_CP_AUTH_SESSION_IDENTITY_SOURCE = "signed_padiem_session_to_identity_shadow_cp_link"


def _is_aware_datetime(value: Any) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _safe_ref(value: Any) -> str:
    if not isinstance(value, str) or _REF_RE.fullmatch(value) is None:
        raise ValueError("invalid_server_reference")
    return value


def validate_canonical_cp_drive_owner_link(
    *,
    owner_b66_user_id: Any,
    cp_auth_session: Any = None,
    cp_connector_context: Any = None,
    now: Any = datetime.now(timezone.utc),
) -> B66VerifiedCPDriveOwnerLink:
    """Build a boundary-safe link from already server-verified host inputs.

    No browser or product-local field may become the CP workspace or actor.
    """

    if not isinstance(owner_b66_user_id, str) or _B66_USER_RE.fullmatch(owner_b66_user_id) is None:
        raise ValueError("invalid_b66_owner")
    if not _is_aware_datetime(now):
        raise ValueError("trusted_time_required")
    if cp_auth_session is None or cp_connector_context is None:
        raise ValueError("cp_host_authority_required")
    subject_id = getattr(cp_auth_session, "subject_id", None)
    if subject_id is None and getattr(cp_auth_session, "subject", None) is not None:
        subject_id = getattr(cp_auth_session.subject, "subject_id", None)
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise ValueError("invalid_canonical_subject")
    is_active = getattr(cp_auth_session, "is_active", None)
    if callable(is_active) and not is_active(now=now):
        raise ValueError("inactive_cp_auth_session")
    workspace_ref = _safe_ref(getattr(cp_connector_context, "workspace_ref", None))
    actor_ref = _safe_ref(getattr(cp_connector_context, "actor_ref", None))
    context_subject_id = getattr(cp_connector_context, "subject_id", None)
    if context_subject_id is not None and context_subject_id != subject_id:
        raise ValueError("cp_subject_mismatch")
    return B66VerifiedCPDriveOwnerLink(
        owner_b66_user_id=owner_b66_user_id,
        cp_workspace_ref=workspace_ref,
        cp_actor_ref=actor_ref,
    )


class UnconfiguredB66HostCPSessionPort:
    """Fail-closed default until a real trusted host resolver is injected."""

    production_host_composition_proven = False

    def resolve_verified_cp_drive_owner_link(self, *args, **kwargs):
        raise ValueError("b66_host_cp_session_not_composed")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "auth_session_to_cp": "IDENTIFIED_UNWIRED",
            "b66_owner_actor_workspace": "BLOCKED",
            "production_host_composition_proven": False,
        }


class B66HostCPSessionFactory:
    """Review a typed resolver seam without claiming production composition."""

    def __init__(self, resolver: Any | None = None) -> None:
        self._resolver = resolver

    @property
    def production_host_composition_proven(self) -> bool:
        return self._resolver is not None and hasattr(self._resolver, "resolve_verified_cp_drive_owner_link")

    def resolve_verified_cp_drive_owner_link(self, owner_b66_user_id, *, now=None):
        if not isinstance(owner_b66_user_id, str) or _B66_USER_RE.fullmatch(owner_b66_user_id) is None:
            raise ValueError("invalid_b66_owner")
        if now is None:
            now = datetime.now(timezone.utc)
        if self._resolver is None:
            raise ValueError("b66_host_cp_session_not_composed")
        return self._resolver.resolve_verified_cp_drive_owner_link(owner_b66_user_id, now=now)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "auth_session_to_cp": "IDENTIFIED_UNWIRED",
            "b66_owner_actor_workspace": "BLOCKED",
            "production_host_composition_proven": self.production_host_composition_proven,
            "server_verified_padiem_session_to_cp_link": True,
            "production_runtime_wired": False,
        }