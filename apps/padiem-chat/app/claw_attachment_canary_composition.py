"""Server-only A6 image-attachment canary seam (#3210).

The smallest production-shaped composition that hands one bounded image from the
existing trusted B54 session to the Engine's canonical multimodal admission
route (``POST /internal/v1/multimodal/attachments``). Nothing here is a new
authority:

* the Engine client is the existing fail-closed Claw P01/Engine composition over
  the Worker's ``P01_ENGINE_*`` bindings and the existing Service Binding
  transport;
* the session identity is the existing trusted server-resolved B54 session
  (``B54BridgedIdentitySession.auth_session.session_id``) — a request payload
  can never name it;
* the reply is the Engine's public-safe attachment projection only
  (``attachment_ref`` / ``media_type`` / ``byte_size`` / ``expires_at``).

The seam stays deliberately route-free: no Worker route, dispatch payload, or
browser-callable path can reach it. This source slice performs no live canary
dispatch, no provider call, and no Production mutation.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_engine_client import PadiemAiEngineClient, PadiemAiEngineClientError
from padiem_control_plane import AuthSessionSnapshot
from padiem_control_plane.b54_identity_bridge import B54BridgedIdentitySession

from .claw_p01_composition import build_claw_engine_client_with_diagnostic

_ATTACHMENT_PROJECTION_FIELDS = (
    "attachment_ref",
    "media_type",
    "byte_size",
    "expires_at",
)
_INVALID_CANARY_SESSION = (
    "The canary seam requires a trusted server-resolved B54 session."
)
_ADMISSION_FAILED = "Image attachment admission failed."


class ClawAttachmentCanaryError(ValueError):
    """Bounded, public-safe failure from the server-only canary seam."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _server_session_id(session: Any) -> str:
    if not isinstance(session, B54BridgedIdentitySession) or not isinstance(
        session.auth_session, AuthSessionSnapshot
    ):
        raise ClawAttachmentCanaryError("invalid_canary_session", _INVALID_CANARY_SESSION)
    session_id = session.auth_session.session_id
    if not isinstance(session_id, str) or not session_id:
        raise ClawAttachmentCanaryError("invalid_canary_session", _INVALID_CANARY_SESSION)
    return session_id


class ClawAttachmentCanary:
    """Server-only admission seam over the one existing Engine client (#3210)."""

    def __init__(self, *, client: PadiemAiEngineClient) -> None:
        if client is None or not callable(getattr(client, "admit_image_attachment", None)):
            raise ValueError("client must expose async admit_image_attachment")
        self._client = client

    async def admit_image_attachment(
        self,
        session: B54BridgedIdentitySession,
        *,
        media_type: str,
        image_base64: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Admit one bounded image for the server-resolved B54 session.

        ``session_id`` is derived here from the trusted B54 session only; the
        seam accepts no caller-supplied session identity. The returned mapping
        carries exactly the public-safe attachment projection.
        """
        request: dict[str, Any] = {
            "session_id": _server_session_id(session),
            "media_type": media_type,
            "image_base64": image_base64,
        }
        if trace_id is not None:
            request["trace_id"] = trace_id
        try:
            projection = await self._client.admit_image_attachment(request)
        except PadiemAiEngineClientError as exc:
            code = (
                exc.code
                if isinstance(exc.code, str) and exc.code
                else "engine_request_failed"
            )
            raise ClawAttachmentCanaryError(code, _ADMISSION_FAILED) from None
        return {name: projection[name] for name in _ATTACHMENT_PROJECTION_FIELDS}


def build_claw_attachment_canary_with_diagnostic(
    env: Any,
    *,
    request_factory: Any,
) -> tuple[ClawAttachmentCanary | None, str | None]:
    """Compose the seam from the existing Worker bindings, or fail closed.

    Diagnostics reuse the closed ``P01_DIAG_*`` vocabulary: a missing or
    malformed binding never constructs a transport and never carries a binding
    value.
    """
    client, diagnostic = build_claw_engine_client_with_diagnostic(
        env, request_factory=request_factory
    )
    if client is None:
        return None, diagnostic
    return ClawAttachmentCanary(client=client), None


def build_claw_attachment_canary(
    env: Any,
    *,
    request_factory: Any,
) -> ClawAttachmentCanary | None:
    """Same fail-closed composition as ``build_claw_attachment_canary_with_diagnostic``."""
    canary, _ = build_claw_attachment_canary_with_diagnostic(
        env, request_factory=request_factory
    )
    return canary


__all__ = [
    "ClawAttachmentCanary",
    "ClawAttachmentCanaryError",
    "build_claw_attachment_canary",
    "build_claw_attachment_canary_with_diagnostic",
]
