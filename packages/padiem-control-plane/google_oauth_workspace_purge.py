"""Account-deletion purge of every Google credential one workspace holds (#7557).

A disconnect only marks a credential ``revoked_at`` and keeps the sealed refresh
token, and nothing asked Google to forget the grant. Account deletion needs
both: the token must stop working at Google, and PADIEM must stop holding it.

One pass, in this order:

1. every credential of the workspace becomes unusable here (one transaction),
   before any provider call, so a later failure never leaves a usable row;
2. for each row: unseal inside the Control Plane, ask Google to revoke the
   grant, then delete the row and its verified destination;
3. a row whose Google revoke failed for a transient reason stays (unusable,
   still sealed) and is counted in ``remaining``. Calling the pass again
   continues with exactly those rows; deleted rows are not revisited.

A row whose envelope can no longer be unsealed can never be revoked at Google
by us, and retrying cannot change that, so it is deleted and counted in
``provider_revoke_skipped`` instead of blocking the deletion forever.

Nothing here returns or logs a token, a binding or a provider identity.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable, Protocol
from urllib.parse import urlencode

from padiem_control_plane.contracts import ControlPlaneContractError

from google_oauth_durable_store import MAX_WORKSPACE_PURGE_CREDENTIALS, _safe_ref
from google_oauth_ingress_runtime import _read_bounded_google_token_response
from google_oauth_webcrypto_sealer import GoogleOAuthSealContext, GoogleOAuthSealPurpose

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

REVOKED = "revoked"
ALREADY_INVALID = "already_invalid"


class GoogleOAuthRevokePort(Protocol):
    async def revoke_token(self, *, token: str) -> str: ...


def _revoke_failed() -> ControlPlaneContractError:
    return ControlPlaneContractError(
        "google_oauth_revoke_failed",
        "Google OAuth grant revocation did not complete",
    )


class CloudflareGoogleOAuthRevokePort:
    """Worker-native call to Google's token revocation endpoint.

    200 means the grant is revoked. 400 ``invalid_token`` means Google no
    longer honours the token (already revoked or expired) — the goal is met.
    Anything else is a transient failure the caller retries.
    """

    async def revoke_token(self, *, token: str) -> str:
        from workers import fetch  # type: ignore[import-not-found]

        try:
            response = await fetch(
                GOOGLE_REVOKE_URL,
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cache-Control": "no-store",
                },
                body=urlencode({"token": token}),
            )
        except Exception as exc:
            raise _revoke_failed() from exc
        return await classify_revoke_response(response)


async def classify_revoke_response(response: Any) -> str:
    status = getattr(response, "status", None)
    if type(status) is not int:
        raise _revoke_failed()
    if status == 200:
        return REVOKED
    if status != 400:
        raise _revoke_failed()
    text = await _read_bounded_google_token_response(
        response,
        error_code="google_oauth_revoke_failed",
        overflow_message="Google OAuth revoke response exceeds the trusted bound",
        invalid_message="Google OAuth revoke response is invalid",
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _revoke_failed() from exc
    if isinstance(payload, dict) and payload.get("error") == "invalid_token":
        return ALREADY_INVALID
    raise _revoke_failed()


class GoogleOAuthWorkspacePurgeRuntime:
    def __init__(
        self,
        *,
        store: Any,
        sealer: Any,
        revoke_port: GoogleOAuthRevokePort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._sealer = sealer
        self._revoke_port = revoke_port
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def purge(self, *, workspace_ref: str) -> dict[str, int]:
        workspace_ref = _safe_ref(workspace_ref, "workspace_ref")
        self._store.revoke_all_workspace_credentials(
            workspace_ref=workspace_ref, revoked_at=self._clock(),
        )
        rows = self._store.workspace_credentials_for_purge(
            workspace_ref=workspace_ref, limit=MAX_WORKSPACE_PURGE_CREDENTIALS,
        )
        purged = skipped = remaining = 0
        for row in rows:
            context = GoogleOAuthSealContext(
                purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
                connector_id=row["connector_id"],
                record_ref=row["binding_ref"],
                actor_ref=row["actor_ref"],
                account_ref=row["account_ref"],
                workspace_ref=row["workspace_ref"],
            )
            token = ""
            try:
                token = await self._sealer.unseal_text(
                    envelope=row["sealed_refresh_token"], context=context,
                )
            except Exception:
                token = ""
            if not token:
                self._store.delete_workspace_credential(
                    workspace_ref=workspace_ref, binding_ref=row["binding_ref"],
                )
                skipped += 1
                continue
            try:
                outcome = await self._revoke_port.revoke_token(token=token)
            except Exception:
                outcome = None
            finally:
                token = ""
            if outcome not in (REVOKED, ALREADY_INVALID):
                remaining += 1
                continue
            self._store.delete_workspace_credential(
                workspace_ref=workspace_ref, binding_ref=row["binding_ref"],
            )
            purged += 1
        # Rows past the per-pass bound are counted so the caller keeps retrying.
        remaining = self._store.count_workspace_credentials(workspace_ref=workspace_ref)
        return {
            "purged": purged,
            "remaining": remaining,
            "provider_revoke_skipped": skipped,
        }
