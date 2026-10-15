"""Engine Google Drive write transport for canonical CP-issued full-scope leases.

#4871: isolated, host-injected create operation for a verified canonical owner.
No OAuth or grant is minted here. No route/tool exposes this port by default.
The trusted authorizer must bind exact actor, workspace, folder and file digest.
Google API is called only after a fresh full-scope CP access lease matches.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import secrets
from typing import Any, Protocol

import httpx

from padiem_ai_core.drive_capability import DRIVE_FULL_SCOPE
from padiem_ai_core.tool_runtime import ToolHandlerError
from app.google_oauth_access_lease import CloudflareControlPlaneGoogleOAuthAccessLeaseClient
from app.service import ServiceContractError


GOOGLE_DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_DRIVE_CREATE_CAPABILITY = "drive.files.create"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_RECEIPT_BYTES = 65_536
MAX_FILENAME_CHARS = 255
MAX_MIME_CHARS = 128
_REF = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/@+\-]{0,255}$")
_MIME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9!#$&^_.+\-]*/[a-zA-Z0-9][a-zA-Z0-9!#$&^_.+\-]*$")
PRODUCTION_DRIVE_CREATE_WIRED = False
LIVE_PROVIDER_WRITE_VERIFIED = False


def _reject(code: str) -> ToolHandlerError:
    # Never echo provider/secret/model body in a public error.
    return ToolHandlerError(code, "Authorized Google Drive file creation is unavailable.")


def _ref(value: str) -> bool:
    return type(value) is str and _REF.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class VerifiedDriveCreateApproval:
    """Host-only projection of an approved exact write intent.

    Dataclass construction is not permission. Production host must provide an
    authentic server-side approval verifier and real CP grant authority.
    """

    binding_ref: str
    actor_ref: str
    workspace_ref: str
    folder_id: str
    filename: str
    mime_type: str
    sha256: str
    capability: str = GOOGLE_DRIVE_CREATE_CAPABILITY


class DriveCreateAuthorizationPort(Protocol):
    async def verify_create(
        self, *, binding_ref: str, actor_ref: str, workspace_ref: str,
        folder_id: str, filename: str, mime_type: str, sha256: str,
    ) -> VerifiedDriveCreateApproval | None: ...


@dataclass(frozen=True, slots=True)
class DriveCreateReceipt:
    file_id: str
    filename: str
    folder_id: str
    mime_type: str
    source_sha256: str

    def safe_dict(self) -> dict[str, str]:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "folder_id": self.folder_id,
            "mime_type": self.mime_type,
            "source_sha256": self.source_sha256,
        }


class ControlPlaneLeaseDriveCreatePort:
    """Official files.create multipart POST with fresh CP lease + write approval.

    The host, never a browser payload, supplies identity refs, file material,
    destination and approval authority. This port neither caches access tokens
    nor retries a potentially successful, non-idempotent provider POST.
    """

    def __init__(
        self, *, lease_client: CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
        authorization: DriveCreateAuthorizationPort,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not callable(getattr(lease_client, "issue_access_lease", None)):
            raise ValueError("trusted CP access-lease client required")
        if not callable(getattr(authorization, "verify_create", None)):
            raise ValueError("trusted Drive write authorization required")
        self._lease_client = lease_client
        self._authorization = authorization
        self._transport = transport

    async def create_file(
        self, *, binding_ref: str, actor_ref: str, workspace_ref: str,
        folder_id: str, filename: str, mime_type: str, content: bytes,
    ) -> DriveCreateReceipt:
        if not all(_ref(x) for x in (binding_ref, actor_ref, workspace_ref, folder_id)):
            raise _reject("google_drive_write_context_invalid")
        if (
            type(filename) is not str or not 1 <= len(filename) <= MAX_FILENAME_CHARS
            or filename in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in filename)
        ):
            raise _reject("google_drive_write_filename_invalid")
        if (
            type(mime_type) is not str or len(mime_type) > MAX_MIME_CHARS
            or _MIME.fullmatch(mime_type) is None
        ):
            raise _reject("google_drive_write_mime_invalid")
        if type(content) is not bytes or not 0 < len(content) <= MAX_UPLOAD_BYTES:
            raise _reject("google_drive_write_body_invalid")
        digest = hashlib.sha256(content).hexdigest()
        expected = VerifiedDriveCreateApproval(
            binding_ref=binding_ref, actor_ref=actor_ref,
            workspace_ref=workspace_ref, folder_id=folder_id,
            filename=filename, mime_type=mime_type, sha256=digest,
        )
        try:
            approval = await self._authorization.verify_create(
                binding_ref=binding_ref, actor_ref=actor_ref,
                workspace_ref=workspace_ref, folder_id=folder_id,
                filename=filename, mime_type=mime_type, sha256=digest,
            )
        except Exception:
            raise _reject("google_drive_write_approval_unavailable") from None
        if type(approval) is not VerifiedDriveCreateApproval or approval != expected:
            raise _reject("google_drive_write_approval_mismatch")

        try:
            lease = await self._lease_client.issue_access_lease(
                binding_ref=binding_ref, connector_id="google-drive",
            )
        except ServiceContractError:
            raise _reject("google_drive_write_lease_unavailable") from None
        except Exception:
            raise _reject("google_drive_write_lease_unavailable") from None
        if (
            lease.binding_ref != binding_ref or lease.actor_ref != actor_ref
            or lease.workspace_ref != workspace_ref
            or lease.connector_id != "google-drive"
            or lease.scopes != (DRIVE_FULL_SCOPE,)
        ):
            raise _reject("google_drive_write_lease_mismatch")

        boundary = "padiem" + secrets.token_hex(16)
        metadata = json.dumps(
            {"name": filename, "mimeType": mime_type, "parents": [folder_id]},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        marker = boundary.encode("ascii")
        body = (
            b"--" + marker + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            + metadata + b"\r\n--" + marker + b"\r\nContent-Type: "
            + mime_type.encode("ascii") + b"\r\n\r\n" + content
            + b"\r\n--" + marker + b"--\r\n"
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=30.0, follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST", GOOGLE_DRIVE_UPLOAD_URL,
                    params={
                        "uploadType": "multipart", "supportsAllDrives": "true",
                        "fields": "id,name,mimeType,parents",
                    },
                    headers={
                        "Authorization": "Bearer " + lease.access_token,
                        "Content-Type": "multipart/related; boundary=" + boundary,
                        "Cache-Control": "no-store",
                    },
                    content=body,
                ) as response:
                    status = response.status_code
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_RECEIPT_BYTES:
                            raise _reject("google_drive_write_receipt_invalid")
        except ToolHandlerError:
            raise
        except (httpx.HTTPError, ValueError):
            raise _reject("google_drive_write_provider_unavailable") from None

        if not 200 <= status < 300:
            raise _reject("google_drive_write_provider_rejected")
        try:
            data: Any = json.loads(bytes(chunks).decode("utf-8"))
        except (ValueError, UnicodeError):
            raise _reject("google_drive_write_receipt_invalid") from None
        if (
            type(data) is not dict or not _ref(data.get("id"))
            or data.get("name") != filename or data.get("mimeType") != mime_type
            or type(data.get("parents")) is not list or folder_id not in data["parents"]
        ):
            raise _reject("google_drive_write_receipt_mismatch")
        return DriveCreateReceipt(
            file_id=data["id"], filename=filename, folder_id=folder_id,
            mime_type=mime_type, source_sha256=digest,
        )
