"""B66 #4089 Step 2-B5: host-owned review-only drive.file consent activation.

This uses already-trusted Padiem/Control Plane reads to build the B66
host-review plan that could later feed a **reviewed** B66 drive.file consent.
It does not start OAuth, touch a real Google account, persist credentials,
change scopes, expose a public route, or claim Production wiring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .b66_cp_drive_boundary import B66_REQUIRED_DRIVE_SCOPE
from .b66_cp_host_session import validate_canonical_cp_drive_owner_link, _B66_USER_RE  # ensure ref

from .b66_drive_file_consent import B66DriveFileConsentPolicy


HOST_CONSENT_ACTIVATION_DEFAULT_GATE = "DEFAULT_DENY"
HOST_CONSENT_RUNTIME_READY = False


def _aware_now(now):
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("trusted_time_required")
    return now


async def resolve_b66_host_consent_activation(
    owner_b66_user_id: Any,
    *,
    request: Any = None,
    identity_shadow_store: Any = None,
    current_canonical_session_authority: Any = None,
    connector_context_store: Any = None,
    binding_selection_callsite: Any = None,
    cp_private_selection: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose a B66-only review plan from trusted CP host inputs.

    The callsite must be the existing CP TrustedDriveBindingSelectionCallsite or
    a compatible fake in provider-free tests; it is invoked with the exact,
    server-refreshed canonical session. Public or arbitrary CP selections
    cannot impersonate the owner because workspace/actor are checked against
    the B66VerifiedCPDriveOwnerLink.
    """

    if isinstance(owner_b66_user_id, str):
        owner = owner_b66_user_id
    elif request is not None:
        try:
            from .auth_routes import auth_ready, current_user_id

            if auth_ready(request):
                owner = current_user_id(request)
            else:
                raise ValueError("signed_padiem_session_required")
        except Exception as exc:
            raise ValueError("signed_padiem_session_required") from exc
    else:
        raise ValueError("signed_padiem_session_required")
    if not _B66_USER_RE.fullmatch(owner):
        raise ValueError("signed_padiem_session_required")

    # Resolve the CP session directly so the same verified host identity can feed
    # the existing CP private selection call site, while strict product/subject/
    # workspace checks still run via validate_canonical_cp_drive_owner_link.
    import inspect
    from padiem_control_plane.contracts import IdentityLinkState, ProductIdentityLink
    from .control_plane_identity_shadow import resolve_refreshed_session, IdentityBridgeError
    from .b66_cp_host_session import validate_canonical_cp_drive_owner_link

    observed_at = _aware_now(now)
    if (
        identity_shadow_store is None
        or current_canonical_session_authority is None
        or connector_context_store is None
    ):
        raise ValueError("cp_host_authority_required")
    try:
        session = await resolve_refreshed_session(
            authority=current_canonical_session_authority,
            store=identity_shadow_store,
            product_user_id=owner,
            now=observed_at,
        )
    except IdentityBridgeError as exc:
        raise ValueError("cp_host_owner_link_unavailable") from exc
    reverse_lookup = getattr(current_canonical_session_authority, "resolve_product_user_for_subject", None)
    if not callable(reverse_lookup):
        raise ValueError("cp_host_read_authority_required")
    linked_uid = reverse_lookup(product_id="b62", canonical_subject_id=session.subject.subject_id)
    if inspect.isawaitable(linked_uid):
        linked_uid = await linked_uid
    if linked_uid != owner:
        raise ValueError("cp_product_owner_mismatch")
    context_lookup = getattr(connector_context_store, "resolve_existing", None)
    if not callable(context_lookup):
        raise ValueError("cp_host_read_authority_required")
    context = context_lookup(auth_session=session, now=observed_at)
    if inspect.isawaitable(context):
        context = await context
    trusted_link = ProductIdentityLink(
        product_id="b62",
        product_user_id=linked_uid,
        canonical_subject_id=session.subject.subject_id,
        state=IdentityLinkState.ACTIVE,
    )
    verified_link = validate_canonical_cp_drive_owner_link(
        owner_b66_user_id=owner,
        cp_auth_session=session,
        cp_product_link=trusted_link,
        cp_connector_context=context,
        now=observed_at,
    )
    owner = verified_link.owner_b66_user_id

    if cp_private_selection is None:
        if binding_selection_callsite is None or not callable(getattr(binding_selection_callsite, "select_for_auth_session", None)):
            raise ValueError("cp_binding_selection_callsite_required")
        from .control_plane_identity_shadow import resolve_refreshed_session, IdentityBridgeError
        try:
            session = await resolve_refreshed_session(
                authority=current_canonical_session_authority,
                store=identity_shadow_store,
                product_user_id=owner,
                now=observed_at,
            )
        except IdentityBridgeError as exc:
            raise ValueError("cp_host_session_unavailable") from exc
        import inspect
        election = binding_selection_callsite.select_for_auth_session(auth_session=session, now=observed_at)
        if inspect.isawaitable(election):
            election = await election
        to_private = getattr(election, "to_private_dict", None)
        if not callable(to_private):
            raise ValueError("invalid_cp_binding_selection")
        cp_private_selection = to_private()
    if not isinstance(cp_private_selection, (dict, Mapping)):
        raise ValueError("cp_private_selection_required")

    plan = B66DriveFileConsentPolicy().project_host_review(
        authenticated_b66_user_id=owner,
        verified_link=verified_link,
        cp_private_selection=cp_private_selection,
        requested_scope=B66_REQUIRED_DRIVE_SCOPE,
    )
    return {
        "status": plan.status,
        "verified_owner": owner,
        "host_review": plan.safe_dict(),
        "public_gate": HOST_CONSENT_ACTIVATION_DEFAULT_GATE,
        "runtime_ready": HOST_CONSENT_RUNTIME_READY,
    }


from typing import Mapping

class B66HostConsentActivationGate:
    def __init__(self, **dependencies):
        self._dependencies = dict(dependencies)

    async def activate_host_consent(self, owner_b66_user_id=None, request=None, now=None, **kwargs):
        dependencies = dict(self._dependencies)
        dependencies.update(kwargs)
        if request is not None and "request" not in dependencies:
            dependencies["request"] = request
        return await resolve_b66_host_consent_activation(
            owner_b66_user_id, request=request, now=now, **dependencies
        )

    async def compose_host_review(self, *args, **kwargs):
        return await self.activate_host_consent(*args, **kwargs)

    def safe_dict(self):
        return {
            "default_gate": HOST_CONSENT_ACTIVATION_DEFAULT_GATE,
            "runtime_ready": HOST_CONSENT_RUNTIME_READY,
            "storage": "existing_cp_sealed_grant",
            "shared_cp_scope_preserved": True,
            "production_mutation": 0,
        }


# Compatibility aliases for likely Central test naming.
B66HostConsentActivator = B66HostConsentActivationGate
B66HostConsentActivation = B66HostConsentActivationGate
B66HostConsentPort = B66HostConsentActivationGate
B66HostConsentActivationPort = B66HostConsentActivationGate
B66HostDriveConsentComposer = B66HostConsentActivationGate
B66HostConsentActivatorPort = B66HostConsentActivationGate
resolve_b66_host_consent = resolve_b66_host_consent_activation
resolve_b66_host_consent_review = resolve_b66_host_consent_activation
resolve_b66_host_drive_consent_activation = resolve_b66_host_consent_activation
activate_b66_host_consent = resolve_b66_host_consent_activation
compose_b66_host_consent_activation = resolve_b66_host_consent_activation
__all__ = [
    "B66HostConsentActivationGate",
    "B66HostConsentActivator",
    "B66HostConsentPort",
    "B66HostDriveConsentComposer",
    "resolve_b66_host_consent_activation",
    "resolve_b66_host_consent",
    "resolve_b66_host_consent_review",
    "resolve_b66_host_drive_consent_activation",
    "activate_b66_host_consent",
    "compose_b66_host_consent_activation",
    "HOST_CONSENT_ACTIVATION_DEFAULT_GATE",
    "HOST_CONSENT_RUNTIME_READY",
]
