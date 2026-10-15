"""B66 #4089: server-owned host wiring for B66 Drive.file consent.

The B66 owner comes only from the signed PADIEM request. The canonical session,
active product link, connector context and B66 Google Drive-file binding are
re-read from the existing private Control Plane authorities. No browser owner,
account, workspace, token, scope, grant reference or credential has authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .auth_routes import auth_ready, current_user_id
from .b66_cp_connector_context import B66CPConnectorContextStore
from .b66_cp_drive_boundary import B66_REQUIRED_DRIVE_SCOPE, _REF_RE
from .b66_cp_host_session import (
    B66VerifiedCPDriveOwnerLink,
    resolve_b66_cp_drive_owner_from_padiem_session,
)
from .b66_drive_connection import (
    B66DriveConnectedAccount,
)
from .control_plane_identity import IdentityBridgeError

B66_GOOGLE_DRIVE_FILE_CONNECTOR = "b66-google-drive-file"
B66_DRIVE_FILE_HOST_SOURCE_READY = True
B66_DRIVE_FILE_HOST_PRODUCTION_WIRED = False
B66_DRIVE_FILE_PROVIDER_HTTP_CONFIGURED = False
B66_DRIVE_FILE_GOOGLE_CREDENTIALS_PERSISTED = "CP_SEALED_DURABLE_OAUTH"

def _observed_now(now: datetime | None) -> datetime:
    observed_at = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("trusted_time_required")
    return observed_at


async def _verified_owner_link(
    *,
    request: Any,
    identity_shadow_store: Any,
    identity_authority: Any,
    now: datetime | None = None,
) -> B66VerifiedCPDriveOwnerLink:
    if request is None or not auth_ready(request):
        raise ValueError("signed_padiem_session_required")
    try:
        owner = current_user_id(request)
    except Exception as exc:
        raise ValueError("signed_padiem_session_required") from exc
    if not isinstance(owner, str) or not owner:
        raise ValueError("signed_padiem_session_required")
    if (
        identity_shadow_store is None
        or identity_authority is None
    ):
        raise ValueError("cp_host_authority_required")

    context_store = B66CPConnectorContextStore(identity_authority)
    return await resolve_b66_cp_drive_owner_from_padiem_session(
        request=request,
        identity_shadow_store=identity_shadow_store,
        current_canonical_session_authority=identity_authority,
        connector_context_store=context_store,
        now=now,
    )


def _selected_binding_actor_matches(selection: dict[str, Any], link: B66VerifiedCPDriveOwnerLink) -> None:
    if not isinstance(selection, dict):
        raise ValueError("invalid_b66_drive_binding")
    if selection.get("connector_id") != B66_GOOGLE_DRIVE_FILE_CONNECTOR:
        raise ValueError("wrong_b66_connector")
    status = selection.get("status")
    if status == "not_connected":
        if set(selection) != {"status", "connector_id", "workspace_ref"}:
            raise ValueError("invalid_b66_drive_binding")
        return
    if status != "resolved":
        raise ValueError("invalid_b66_drive_binding")
    if any(not isinstance(selection.get(key), str) or not selection.get(key) for key in ("binding_ref", "actor_ref", "provider_subject")):
        raise ValueError("invalid_b66_drive_binding")
    if not _REF_RE.fullmatch(selection["actor_ref"]):
        raise ValueError("invalid_b66_drive_binding")
    if selection["actor_ref"] != link.cp_actor_ref:
        raise ValueError("b66_actor_mismatch")
    if not _REF_RE.fullmatch(selection["workspace_ref"]) or selection["workspace_ref"] != link.cp_workspace_ref:
        raise ValueError("b66_workspace_mismatch")
    provider_email = selection.get("provider_email")
    if provider_email is not None and (
        not isinstance(provider_email, str) or "@" not in provider_email or len(provider_email) > 320
    ):
        raise ValueError("invalid_b66_drive_binding")


def _public_status(owner: str, selection: dict[str, Any]) -> dict[str, Any]:
    if selection.get("status") != "resolved":
        return {
            "status": "not_connected",
            "verified_store_owner": owner,
            "destination_account": None,
            "destination_sub": None,
            "scope": B66_REQUIRED_DRIVE_SCOPE,
            "reconnect_reason": None,
            "connected_at": None,
            "durable_credential_backend": B66_DRIVE_FILE_GOOGLE_CREDENTIALS_PERSISTED,
        }
    account = B66DriveConnectedAccount(
        google_sub=selection["provider_subject"],
        email=selection.get("provider_email"),
    )
    return {
        "status": "connected",
        "verified_store_owner": owner,
        "destination_account": account.display_value,
        "destination_sub": account.google_sub,
        "scope": B66_REQUIRED_DRIVE_SCOPE,
        "reconnect_reason": None,
        "connected_at": None,
        "durable_credential_backend": B66_DRIVE_FILE_GOOGLE_CREDENTIALS_PERSISTED,
    }


class B66DriveFileHost:
    """Compose signed B66 owner identity with the existing CP authorities."""

    production_host_wiring = B66_DRIVE_FILE_HOST_PRODUCTION_WIRED

    def __init__(
        self,
        *,
        identity_shadow_store: Any,
        identity_authority: Any,
        google_oauth_authority: Any,
    ) -> None:
        if identity_shadow_store is None or identity_authority is None or google_oauth_authority is None:
            raise ValueError("b66_host_authorities_required")
        self._identity_shadow_store = identity_shadow_store
        self._identity_authority = identity_authority
        self._google_oauth_authority = google_oauth_authority

    async def start_connect(self, *, request: Any, now: datetime | None = None) -> dict[str, Any]:
        observed_at = _observed_now(now)
        link = await _verified_owner_link(
            request=request,
            identity_shadow_store=self._identity_shadow_store,
            identity_authority=self._identity_authority,
            now=observed_at,
        )
        if link.cp_session_id is None:
            raise ValueError("cp_session_unavailable")
        issue_ticket = getattr(self._identity_authority, "issue_b66_google_drive_file_connect_ticket", None)
        begin_connect = getattr(self._google_oauth_authority, "begin_b66_drive_connect", None)
        if not callable(issue_ticket) or not callable(begin_connect):
            raise ValueError("b66_connect_authority_unavailable")
        try:
            receipt = await issue_ticket(session_id=link.cp_session_id)
            authorization = await begin_connect(connect_ticket=receipt.connect_ticket)
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise ValueError("b66_drive_connect_unavailable") from exc
        if not isinstance(authorization, dict):
            raise ValueError("invalid_b66_connect_authorization")
        return {"status": "connect_started", "authorization": authorization}

    async def complete_callback(
        self,
        *,
        request: Any,
        state_ref: str,
        authorization_code: str | None,
        provider_error: str | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        complete = getattr(self._google_oauth_authority, "complete_b66_drive_callback", None)
        if not callable(complete):
            raise ValueError("b66_connect_authority_unavailable")
        try:
            connection = await complete(
                state_ref=state_ref,
                authorization_code=authorization_code,
                provider_error=provider_error,
            )
        except Exception as exc:
            raise ValueError("b66_drive_connect_unavailable") from exc

        observed_at = _observed_now(now)
        link = await _verified_owner_link(
            request=request,
            identity_shadow_store=self._identity_shadow_store,
            identity_authority=self._identity_authority,
            now=observed_at,
        )
        selection = await self._select_binding(link)
        _selected_binding_actor_matches(selection, link)
        if selection["status"] != "resolved":
            raise ValueError("b66_drive_connect_not_usable")
        if connection.get("verified_destination_subject") != selection["provider_subject"]:
            raise ValueError("b66_drive_connect_destination_mismatch")
        return _public_status(link.owner_b66_user_id, selection)

    async def status(self, *, request: Any, now: datetime | None = None) -> dict[str, Any]:
        observed_at = _observed_now(now)
        link = await _verified_owner_link(
            request=request,
            identity_shadow_store=self._identity_shadow_store,
            identity_authority=self._identity_authority,
            now=observed_at,
        )
        selection = await self._select_binding(link)
        _selected_binding_actor_matches(selection, link)
        return _public_status(link.owner_b66_user_id, selection)

    async def disconnect(self, *, request: Any, now: datetime | None = None) -> dict[str, Any]:
        observed_at = _observed_now(now)
        link = await _verified_owner_link(
            request=request,
            identity_shadow_store=self._identity_shadow_store,
            identity_authority=self._identity_authority,
            now=observed_at,
        )
        selection = await self._select_binding(link)
        _selected_binding_actor_matches(selection, link)
        disconnect = getattr(self._google_oauth_authority, "disconnect_b66_drive", None)
        if not callable(disconnect):
            raise ValueError("b66_disconnect_authority_unavailable")
        try:
            revoked = await disconnect(workspace_ref=link.cp_workspace_ref)
        except Exception as exc:
            raise ValueError("b66_drive_disconnect_unavailable") from exc
        if not isinstance(revoked, bool):
            raise ValueError("invalid_b66_disconnect_result")
        status = _public_status(link.owner_b66_user_id, selection if revoked is False else {
            "status": "not_connected"
        })
        return {"revoked": revoked, "status": status}

    async def _select_binding(self, link: B66VerifiedCPDriveOwnerLink) -> dict[str, Any]:
        select_binding = getattr(self._google_oauth_authority, "select_b66_drive_binding", None)
        if not callable(select_binding):
            raise ValueError("b66_binding_authority_unavailable")
        try:
            selection = await select_binding(workspace_ref=link.cp_workspace_ref)
        except Exception as exc:
            raise ValueError("b66_drive_binding_unavailable") from exc
        if not isinstance(selection, dict):
            raise ValueError("invalid_b66_drive_binding")
        return selection


B66_DRIVE_FILE_HOST_ROUTE_BOUNDARY = "server_only"
