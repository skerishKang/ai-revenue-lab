"""B66 #4089: canonical CP host connector-context read adapter for server host code.

This module supplies the B66 host with the Control Plane's own actor/workspace/
subject context for one existing canonical session. It never accepts browser
assertions, never mints connector context, never returns sealed material, and
fails closed when the canonical context is absent or belongs to another session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
from typing import Any

from padiem_control_plane import AuthSessionSnapshot

from .control_plane_identity import PADIEM_CHAT_PRODUCT_ID


B66_CP_CONNECTOR_CONTEXT_SOURCE = "cp_private_connector_context_rpc"
B66_CP_CONNECTOR_CONTEXT_RUNTIME_WIRED = True
B66_CP_CONNECTOR_CONTEXT_PRODUCTION_WIRED = False


@dataclass(frozen=True, slots=True)
class B66CPConnectorContext:
    """Server-derived canonical context fields needed by the B66 host gate."""

    product_id: str
    subject_id: str
    actor_ref: str
    workspace_ref: str


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class B66CPConnectorContextStore:
    """Read the trusted Control Plane context through the B62 worker adapter."""

    production_wired = B66_CP_CONNECTOR_CONTEXT_PRODUCTION_WIRED

    def __init__(self, identity_authority: Any) -> None:
        if identity_authority is None:
            raise ValueError("cp_identity_authority_required")
        self._identity_authority = identity_authority

    async def resolve_existing(
        self,
        *,
        auth_session: Any,
        now: datetime | None = None,
    ) -> B66CPConnectorContext | None:
        if not isinstance(auth_session, AuthSessionSnapshot):
            raise ValueError("invalid_cp_auth_session")
        observed_at = now if now is not None else datetime.now(timezone.utc)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("trusted_time_required")
        if auth_session.product_id != PADIEM_CHAT_PRODUCT_ID:
            raise ValueError("cp_product_mismatch")
        if not auth_session.is_active(now=observed_at):
            raise ValueError("inactive_cp_auth_session")

        resolver = getattr(self._identity_authority, "resolve_connector_context", None)
        if not callable(resolver):
            raise ValueError("cp_host_read_authority_required")
        context = await _maybe_await(
            resolver(session_id=auth_session.session_id)
        )
        if context is None:
            return None
        if not isinstance(context, dict):
            raise ValueError("invalid_cp_connector_context")
        if context.get("product_id") != PADIEM_CHAT_PRODUCT_ID:
            raise ValueError("cp_product_mismatch")
        if context.get("subject_id") != auth_session.subject.subject_id:
            raise ValueError("cp_subject_mismatch")
        actor_ref = context.get("actor_ref")
        workspace_ref = context.get("workspace_ref")
        if not isinstance(actor_ref, str) or not actor_ref:
            raise ValueError("invalid_cp_connector_context")
        if not isinstance(workspace_ref, str) or not workspace_ref:
            raise ValueError("invalid_cp_connector_context")
        return B66CPConnectorContext(
            product_id=PADIEM_CHAT_PRODUCT_ID,
            subject_id=auth_session.subject.subject_id,
            actor_ref=actor_ref,
            workspace_ref=workspace_ref,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "context_source": B66_CP_CONNECTOR_CONTEXT_SOURCE,
            "client_asserted_actor_workspace": False,
            "mint_on_read": False,
            "runtime_wired": B66_CP_CONNECTOR_CONTEXT_RUNTIME_WIRED,
            "production_wired": self.production_wired,
        }
