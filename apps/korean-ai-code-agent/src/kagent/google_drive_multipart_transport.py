"""#3580 Google Drive files.create binary transport behind canonical WRITE grant.

This concrete port performs one TLS POST, but DOES NOT mint connector authority:
the existing artifact adapter checks WRITE scope, folder, approval and payload.
A separately composed Control Plane credential resolver must authorize the
*exact* binding/actor/capability and supply a short-lived access token.
No OAuth refresh, token store or grant is created here; not Production-wired.
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol
from urllib.parse import urlencode

from .contracts import ContractError
from .google_drive_artifact_upload import (
    DRIVE_UPLOAD_PATH, DRIVE_UPLOAD_QUERY, DRIVE_UPLOAD_CAPABILITY,
    MAX_UPLOAD_BYTES, MULTIPART_OVERHEAD_MAX, TIMEOUT_SECONDS,
)
from .google_oauth_authority import (
    GoogleProviderNetworkPort, StdlibGoogleProviderNetwork,
)

PRODUCTION_DRIVE_WRITE_PORT_COMPOSED = False
NEW_GOOGLE_OAUTH_AUTHORITY = False
LIVE_PROVIDER_CANARY = False
AUTO_RETRY = False

MAX_DRIVE_RECEIPT_BYTES = 64 * 1024
GOOGLE_UPLOAD_ORIGIN = "https://www.googleapis.com"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_BOUNDARY = re.compile(r"^multipart/related; boundary=(padiem[a-f0-9]{32})$")


class DriveAuthorizedWriteTokenPort(Protocol):
    """Implemented by existing CP connector secret/WRITE-lease authority only."""

    def resolve_write_access_token(
        self, *, binding_ref: str, actor_ref: str, capability: str,
    ) -> str: ...


class UnconfiguredDriveAuthorizedWriteTokenPort:
    def resolve_write_access_token(self, **_: Any) -> str:
        raise ContractError("Google Drive WRITE connector authority is not configured")


class StdlibGoogleDriveMultipartCreatePort:
    """One physical POST; no redirect/retry or model/customer chosen endpoint.

    The caller must be GoogleDriveArtifactUploadAdapter after its existing
    scoped, human-approved WRITE intent. The credential provider is injected
    by the existing canonical connector host, not supplied in tool arguments.
    """

    def __init__(
        self, *,
        authorization: DriveAuthorizedWriteTokenPort | None = None,
        network: GoogleProviderNetworkPort | None = None,
    ) -> None:
        self._authorization = authorization or UnconfiguredDriveAuthorizedWriteTokenPort()
        self._network = network or StdlibGoogleProviderNetwork()

    def create_file_multipart(
        self, *, binding_ref: str, actor_ref: str, path: str,
        query: dict[str, str], body: bytes, content_type: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        # Refuse invalid instructions BEFORE asking the secret-bearing port.
        if (type(binding_ref) is not str or not _REF.fullmatch(binding_ref)
                or type(actor_ref) is not str or not _REF.fullmatch(actor_ref)):
            raise ContractError("trusted connector binding and actor references required")
        if path != DRIVE_UPLOAD_PATH or type(query) is not dict or query != DRIVE_UPLOAD_QUERY:
            raise ContractError("only Google Drive new-file multipart create is allowed")
        if type(timeout_seconds) is not int or timeout_seconds != TIMEOUT_SECONDS:
            raise ContractError("untrusted upload timeout")
        if type(body) is not bytes or not 0 < len(body) <= MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_MAX + 1024:
            raise ContractError("Google Drive multipart request exceeds size bound")
        if type(content_type) is not str or not _BOUNDARY.fullmatch(content_type):
            raise ContractError("Google Drive multipart boundary is invalid")
        boundary = _BOUNDARY.fullmatch(content_type).group(1).encode("ascii")
        if (not body.startswith(b"--" + boundary + b"\r\n")
                or not body.endswith(b"\r\n--" + boundary + b"--\r\n")):
            raise ContractError("Google Drive multipart boundaries do not match")
        if b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" not in body:
            raise ContractError("Google Drive metadata part missing")

        try:
            token = self._authorization.resolve_write_access_token(
                binding_ref=binding_ref, actor_ref=actor_ref,
                capability=DRIVE_UPLOAD_CAPABILITY,
            )
        except Exception:
            # Refuse leaking a credential resolver's exception / provider info.
            raise ContractError("authorized Google Drive WRITE access unavailable") from None
        if (
            type(token) is not str
            or not 12 <= len(token) <= 8192
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in token)
        ):
            raise ContractError("authorized Google Drive WRITE access unavailable")

        url = GOOGLE_UPLOAD_ORIGIN + path + "?" + urlencode(sorted(query.items()))
        try:
            response = self._network.request(
                method="POST", url=url,
                headers={
                    "authorization": "Bearer " + token,
                    "accept": "application/json",
                    "cache-control": "no-store",
                    "content-type": content_type,
                    "content-length": str(len(body)),
                    "user-agent": "padiem-claw-drive-artifact/0.1",
                },
                body=body,
                timeout_seconds=TIMEOUT_SECONDS,
                max_response_bytes=MAX_DRIVE_RECEIPT_BYTES,
            )
        except Exception:
            # No raw HTTP, body, token, local path or provider message to model.
            raise ContractError("Google Drive WRITE network operation failed") from None

        if type(response.status) is not int or not 200 <= response.status <= 299:
            raise ContractError("Google Drive WRITE did not succeed")
        if type(response.body) is not bytes or not 0 < len(response.body) <= MAX_DRIVE_RECEIPT_BYTES:
            raise ContractError("Google Drive WRITE returned invalid response")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise ContractError("Google Drive WRITE returned invalid JSON") from None
        if type(payload) is not dict:
            raise ContractError("Google Drive WRITE returned invalid metadata")
        # No *provider success* claim here: the existing upload adapter still
        # verifies returned file id, parent, size and checksum before durability.
        return payload
