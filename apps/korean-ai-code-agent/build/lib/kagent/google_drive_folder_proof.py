"""#3580 DriveFolderProofPort over the existing authorized Drive READ seam.

``google_drive_artifact_upload.py`` refuses to create a new Drive file until it
holds a trusted ``DriveResourceProof`` of the *destination folder* and has
re-authorized that proof against the Drive scope. No host implementation of that
port existed, so the Drive WRITE path could not be composed even after a WRITE
grant is issued.

This module is that implementation. It introduces no authority of its own:

```text
WHAT THIS FILE IS
  A read-only adapter from the existing authorized Drive READ seam
  (``kagent.google_drive_connector.AuthorizedGoogleDriveHttpPort`` — the same
  seam ``GoogleDriveReadTransport`` already uses) to ``DriveFolderProofPort``.

WHAT IT IS NOT
  Not an OAuth authority, not a token store, not a scope decision and not a
  WRITE path. It performs exactly one bounded ``files.get`` per call, returns a
  truthful proof or ``None``, and never widens, mints or caches a grant. The
  upload adapter remains the single authority that decides whether the proof is
  in scope; this port cannot authorize anything by itself.
```

The proof is deliberately narrow: the caller must already hold a trusted
binding/actor pair, the requested id must come back as the *same* id, the
resource must be a real (non-shortcut) folder, and it must not be trashed. Any
provider, transport or validation doubt yields ``None`` — never a partial proof.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .contracts import ContractError
from .google_drive_artifact_upload import DRIVE_FOLDER_MIME
from .google_drive_connector import (
    AuthorizedGoogleDriveHttpPort, REQUEST_TIMEOUT_SECONDS,
)
from .google_drive_scope import DriveFileMetadata, DriveResourceProof

DRIVE_API_BASE_URL = "https://www.googleapis.com/drive/v3"

#: Only the fields a folder proof needs. ``version`` is required by
#: ``DriveFileMetadata``; ``shortcutDetails`` lets a shortcut be recognised and
#: refused instead of being mistaken for a folder.
FOLDER_PROOF_FIELDS = (
    "id,name,mimeType,version,parents,driveId,trashed,"
    "shortcutDetails(targetId,targetMimeType,targetResourceKey)"
)

#: Static contract markers for this read-only slice.
READ_ONLY_PORT = True
NEW_DRIVE_AUTHORITY = False
NEW_OAUTH_AUTHORITY = False
NEW_SCOPE_AUTHORITY = False
AUTO_RETRY = False
RAW_CREDENTIAL_IN_PORT = False
PRODUCTION_FOLDER_PROOF_COMPOSED = False

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


class DriveFolderProofError(ContractError):
    """Fail-closed construction error; never carries provider material."""


def _trusted_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise DriveFolderProofError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise DriveFolderProofError(f"{field_name} must be a bounded safe reference")
    return normalized


class AuthorizedDriveFolderProofPort:
    """``DriveFolderProofPort`` implemented on the existing Drive READ seam.

    Deliberately holds no credential, no scope and no cache: every call goes
    through the injected authorized READ port, which resolves and refreshes the
    credential outside task/model state.
    """

    def __init__(self, *, http: AuthorizedGoogleDriveHttpPort) -> None:
        if not callable(getattr(http, "get_json", None)):
            raise DriveFolderProofError("authorized Drive READ port is required")
        self._http = http

    def resolve_folder_proof(
        self, *, binding_ref: str, actor_ref: str, folder_ref: str,
    ) -> DriveResourceProof | None:
        """Return a truthful folder proof, or ``None`` on any doubt.

        ``None`` is the fail-closed answer the upload adapter already treats as
        "trusted Drive folder proof required"; it is never a partial or assumed
        proof.
        """
        try:
            binding = _trusted_ref(binding_ref, "binding_ref")
            actor = _trusted_ref(actor_ref, "actor_ref")
            folder = _trusted_ref(folder_ref, "folder_ref")
        except DriveFolderProofError:
            return None
        if "/" in folder:
            # A folder id is an opaque id, never a path.
            return None

        try:
            raw = self._http.get_json(
                binding_ref=binding,
                actor_ref=actor,
                base_url=DRIVE_API_BASE_URL,
                path="/files/" + quote(folder, safe=""),
                query={"fields": FOLDER_PROOF_FIELDS, "supportsAllDrives": "true"},
                timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception:
            # OAuth, HTTP and provider failures can carry private headers and
            # body text. Never forward exception details or provider messages.
            return None
        if type(raw) is not dict:
            return None
        try:
            metadata = DriveFileMetadata.from_provider(raw)
        except ContractError:
            return None

        # The returned resource must be the exact folder that was asked for, a
        # real folder, and live. A shortcut is not a folder and must never be
        # accepted as a WRITE destination.
        if (
            metadata.file_id != folder
            or metadata.mime_type != DRIVE_FOLDER_MIME
            or metadata.is_shortcut
            or metadata.trashed
        ):
            return None
        return DriveResourceProof(binding_ref=binding, metadata=metadata)


__all__ = [
    "AuthorizedDriveFolderProofPort",
    "DRIVE_API_BASE_URL",
    "DriveFolderProofError",
    "FOLDER_PROOF_FIELDS",
    "NEW_DRIVE_AUTHORITY",
    "NEW_OAUTH_AUTHORITY",
    "NEW_SCOPE_AUTHORITY",
    "PRODUCTION_FOLDER_PROOF_COMPOSED",
    "READ_ONLY_PORT",
]
