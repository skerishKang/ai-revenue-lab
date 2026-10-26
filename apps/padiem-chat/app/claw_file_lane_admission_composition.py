"""Server-only COM2 document-reference admission seam for Claw (#5881 stage 4).

The smallest production-shaped composition that hands one file reference to the
Engine's canonical document admission route (``POST /internal/v1/documents``)
so the Engine, not this process, reads the lane's extracted text. Nothing here
is a new authority:

* the Engine client is the existing fail-closed Claw P01/Engine composition over
  the Worker's ``P01_ENGINE_*`` bindings and the same Service Binding transport;
* the session identity is the existing trusted server-resolved B54 session — a
  request payload can never name it;
* the read claim is the existing #5893 ticket mint on ``FileLaneClient``, minted
  fresh inside this call so the Engine always presents it within its own
  lifetime, and its values are forwarded unchanged;
* the reply is the Engine's document receipt projection only.

The seam stays deliberately route-free: no Worker route, dispatch payload, or
browser-callable path reaches it, and no document text enters this process. A
deployment without the file lane (``PADIEM_CHAT_FILE_LANE_ORIGIN`` unset) never
constructs it, so the existing inline attachment path is untouched. This source
slice performs no live admission dispatch and no Production mutation.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_engine_client import (
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)
from padiem_control_plane import AuthSessionSnapshot
from padiem_control_plane.b54_identity_bridge import B54BridgedIdentitySession

from .claw_p01_composition import build_claw_engine_client_with_diagnostic

DOCUMENT_PROJECTION_FIELDS = (
    "document_ref",
    "media_type",
    "byte_size",
    "expires_at",
    "total_chars",
    "next_offset",
    "window_eof",
)
_INVALID_ADMISSION_SESSION = (
    "The admission seam requires a trusted server-resolved B54 session."
)
_ADMISSION_FAILED = "COM2 document reference admission failed."
# A lane without its configured origin/secret has no claim to hand the Engine.
# Reported as a name only: never a value, never a secret length.
FILE_LANE_DIAGNOSTIC = "FILE_LANE_UNCONFIGURED"


class ClawFileLaneAdmissionError(ValueError):
    """Bounded, public-safe failure from the server-only admission seam."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _server_session_id(session: Any) -> str:
    if not isinstance(session, B54BridgedIdentitySession) or not isinstance(
        session.auth_session, AuthSessionSnapshot
    ):
        raise ClawFileLaneAdmissionError("invalid_admission_session", _INVALID_ADMISSION_SESSION)
    session_id = session.auth_session.session_id
    if not isinstance(session_id, str) or not session_id:
        raise ClawFileLaneAdmissionError("invalid_admission_session", _INVALID_ADMISSION_SESSION)
    return session_id


class ClawFileLaneDocumentAdmission:
    """Server-only reference admission over the one existing Engine client."""

    def __init__(self, *, client: PadiemAiEngineClient, file_lane: Any) -> None:
        if client is None or not callable(getattr(client, "admit_document_reference", None)):
            raise ValueError("client must expose async admit_document_reference")
        if file_lane is None or not callable(getattr(file_lane, "read_ticket", None)):
            raise ValueError("file_lane must expose read_ticket")
        self._client = client
        self._file_lane = file_lane

    async def admit(
        self,
        session: B54BridgedIdentitySession,
        *,
        user_id: str,
        file_id: str,
        sha256: str,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Admit one reference for the server-resolved session and owner.

        ``user_id`` is the already verified owner (the same value the browser
        upload and the inline read path use); the ticket is minted here, so a
        claim produced earlier — possibly near its expiry — is never replayed.
        """
        session_id = _server_session_id(session)
        headers, _expires = self._file_lane.read_ticket(user_id)
        request: dict[str, Any] = {
            "session_id": session_id,
            "file_id": file_id,
            "sha256": sha256,
            "file_ticket": headers,
        }
        if filename is not None:
            request["filename"] = filename
        try:
            projection = await self._client.admit_document_reference(request)
        except PadiemAiEngineClientError as exc:
            code = (
                exc.code
                if isinstance(exc.code, str) and exc.code
                else "engine_request_failed"
            )
            raise ClawFileLaneAdmissionError(code, _ADMISSION_FAILED) from None
        return {name: projection[name] for name in DOCUMENT_PROJECTION_FIELDS}


def build_claw_file_lane_document_admission_with_diagnostic(
    env: Any,
    *,
    request_factory: Any,
    file_lane: Any,
) -> tuple[ClawFileLaneDocumentAdmission | None, str | None]:
    """Compose the seam from the existing Worker bindings, or fail closed.

    The Engine half reuses the closed ``P01_DIAG_*`` vocabulary. The lane half
    answers ``FILE_LANE_DIAGNOSTIC``: a lane without its configured origin and
    secret has no claim to hand over, so the caller keeps the inline path
    instead of reaching an Engine route that would refuse it.
    """
    if file_lane is None or not callable(getattr(file_lane, "read_ticket", None)):
        return None, FILE_LANE_DIAGNOSTIC
    if not getattr(file_lane, "ready", False):
        return None, FILE_LANE_DIAGNOSTIC
    client, diagnostic = build_claw_engine_client_with_diagnostic(
        env, request_factory=request_factory
    )
    if client is None:
        return None, diagnostic
    return ClawFileLaneDocumentAdmission(client=client, file_lane=file_lane), None


def build_claw_file_lane_document_admission(
    env: Any,
    *,
    request_factory: Any,
    file_lane: Any,
) -> ClawFileLaneDocumentAdmission | None:
    """Same fail-closed composition as the ``_with_diagnostic`` builder."""
    admission, _ = build_claw_file_lane_document_admission_with_diagnostic(
        env, request_factory=request_factory, file_lane=file_lane
    )
    return admission


__all__ = [
    "ClawFileLaneAdmissionError",
    "ClawFileLaneDocumentAdmission",
    "DOCUMENT_PROJECTION_FIELDS",
    "FILE_LANE_DIAGNOSTIC",
    "build_claw_file_lane_document_admission",
    "build_claw_file_lane_document_admission_with_diagnostic",
]
