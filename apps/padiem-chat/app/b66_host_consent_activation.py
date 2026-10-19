"""B66 #4089: server-only reviewed Drive FILE consent plan (NOT OAuth activation).

The authenticated product owner is derived ONLY from the verified PADIEM
request, then checked against refreshed CP session, ACTIVE reverse product link,
and the existing server-owned connector context.  CP's reviewed Drive READ
selection cannot grant the B66 WRITE scope.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

from padiem_control_plane.contracts import IdentityLinkState, ProductIdentityLink

from .auth_routes import auth_ready, current_user_id
from .b66_cp_drive_boundary import B66_REQUIRED_DRIVE_SCOPE, _B66_USER_RE
from .b66_cp_host_session import validate_canonical_cp_drive_owner_link
from .b66_drive_file_consent import B66DriveFileConsentPolicy
from .control_plane_identity_shadow import resolve_refreshed_session

HOST_CONSENT_ACTIVATION_DEFAULT_GATE = "DEFAULT_DENY"
HOST_CONSENT_RUNTIME_READY = False


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def resolve_b66_host_consent_activation(
    *,
    request: Any,
    identity_shadow_store: Any,
    current_canonical_session_authority: Any,
    connector_context_store: Any,
    binding_selection_callsite: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Construct only a non-executable, private host review plan.

    Neither owner_b66_user_id nor cp_private_selection is accepted as input:
    browser/caller values cannot replace the PADIEM signed session and CP's
    private selection authority. The host must inject trusted CP readers.
    """
    observed_at = now if now is not None else datetime.now(timezone.utc)
    if (
        not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        raise ValueError("trusted_time_required")
    if request is None or not auth_ready(request):
        raise ValueError("signed_padiem_session_required")
    try:
        owner = current_user_id(request)
    except Exception as exc:
        raise ValueError("signed_padiem_session_required") from exc
    if not isinstance(owner, str) or _B66_USER_RE.fullmatch(owner) is None:
        raise ValueError("signed_padiem_session_required")

    if (
        identity_shadow_store is None
        or current_canonical_session_authority is None
        or connector_context_store is None
        or binding_selection_callsite is None
    ):
        raise ValueError("cp_host_authority_required")
    reverse_lookup = getattr(
        current_canonical_session_authority, "resolve_product_user_for_subject", None
    )
    context_lookup = getattr(connector_context_store, "resolve_existing", None)
    selection_lookup = getattr(
        binding_selection_callsite, "select_for_auth_session", None
    )
    if not all(callable(fn) for fn in (reverse_lookup, context_lookup, selection_lookup)):
        raise ValueError("cp_host_read_authority_required")

    try:
        session = await resolve_refreshed_session(
            authority=current_canonical_session_authority,
            store=identity_shadow_store,
            product_user_id=owner,
            now=observed_at,
        )
        canonical_subject_id = session.subject.subject_id
        linked_user = await _await_if_needed(reverse_lookup(
            product_id="b62", canonical_subject_id=canonical_subject_id,
        ))
        if linked_user != owner:
            raise ValueError("cp_product_owner_mismatch")

        context = await _await_if_needed(context_lookup(
            auth_session=session, now=observed_at,
        ))
        if (
            getattr(context, "product_id", None) != "b62"
            or getattr(context, "subject_id", None) != canonical_subject_id
        ):
            raise ValueError("cp_connector_context_mismatch")

        product_link = ProductIdentityLink(
            product_id="b62",
            product_user_id=linked_user,
            canonical_subject_id=canonical_subject_id,
            state=IdentityLinkState.ACTIVE,
        )
        verified_link = validate_canonical_cp_drive_owner_link(
            owner_b66_user_id=owner,
            cp_auth_session=session,
            cp_product_link=product_link,
            cp_connector_context=context,
            now=observed_at,
        )
        selection = await _await_if_needed(selection_lookup(
            auth_session=session, now=observed_at,
        ))
        to_private = getattr(selection, "to_private_dict", None)
        if not callable(to_private):
            raise ValueError("invalid_cp_binding_selection")
        private_selection = to_private()
        plan = B66DriveFileConsentPolicy().project_host_review(
            authenticated_b66_user_id=owner,
            verified_link=verified_link,
            cp_private_selection=private_selection,
            requested_scope=B66_REQUIRED_DRIVE_SCOPE,
        )
    except Exception as exc:
        # Never disclose CP authority or Google provider material in public logs.
        raise ValueError("b66_host_consent_review_unavailable") from exc
    return {
        "status": plan.status,
        "host_review": plan.safe_dict(),
        "public_gate": HOST_CONSENT_ACTIVATION_DEFAULT_GATE,
        "runtime_ready": HOST_CONSENT_RUNTIME_READY,
    }


class B66HostConsentActivationGate:
    """Accept only injection-time trusted CP services, never request overrides."""

    def __init__(
        self,
        *,
        identity_shadow_store: Any = None,
        current_canonical_session_authority: Any = None,
        connector_context_store: Any = None,
        binding_selection_callsite: Any = None,
    ) -> None:
        self._host = dict(
            identity_shadow_store=identity_shadow_store,
            current_canonical_session_authority=current_canonical_session_authority,
            connector_context_store=connector_context_store,
            binding_selection_callsite=binding_selection_callsite,
        )

    async def compose_host_review(
        self, *, request: Any, now: datetime | None = None,
    ) -> dict[str, Any]:
        return await resolve_b66_host_consent_activation(
            request=request, now=now, **self._host,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "default_gate": HOST_CONSENT_ACTIVATION_DEFAULT_GATE,
            "runtime_ready": HOST_CONSENT_RUNTIME_READY,
            "storage": "existing_cp_sealed_grant_not_yet_connected",
            "shared_cp_scope_preserved": True,
            "production_mutation": 0,
        }


__all__ = [
    "B66HostConsentActivationGate",
    "resolve_b66_host_consent_activation",
    "HOST_CONSENT_ACTIVATION_DEFAULT_GATE",
    "HOST_CONSENT_RUNTIME_READY",
]
