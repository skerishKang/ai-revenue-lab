"""#2505: one attachment boundary for the Chat and the Claw turn.

Chat already owns the attachment grammar (``app/attachments.py``) and the
provider-bound document text contract (``app/documents.py``). The Claw turn
reuses both instead of growing a second parser, a second normalizer or a second
reference-context preamble:

* the browser sends the same ``attachments`` array on ``POST /api/claw/general``
  that it already sends on ``POST /api/chat``;
* a document becomes the same untrusted reference context Chat builds, so the
  model reads it as data and never as an instruction;
* the document text travels on the existing ``additional_system_context`` seam
  the Claw lane already uses for grounded/PC context. No new Engine argument,
  provider route or storage record is introduced.

An image stays unsupported on this lane. That is not a product policy choice:
the canonical P01 Engine execution request has no image input at all. The
Engine's image admission seam (``POST /internal/v1/multimodal/attachments``)
mints an opaque ``att_*`` reference, and no orchestration request type carries
that reference yet (#3210 is a server-only composition with no route). Refusing
the image here keeps the turn from claiming that a picture was read when
nothing read it; the caller can still attach the same image on Chat.
"""

from __future__ import annotations

from typing import Any

from .attachments import (
    AttachmentValidationError,
    ImageAttachment,
    parse_attachments,
    parse_attachments_async,
)
from .documents import DocumentAttachment, build_documents_context

#: The Claw lane cannot hand image bytes to its model yet.
CLAW_IMAGE_ATTACHMENT_UNSUPPORTED = (
    "Claw는 아직 사진 첨부를 모델에 전달할 수 없습니다. 사진은 Chat에서 사용해 주세요."
)


def _project_attachments(
    attachments: tuple[ImageAttachment | DocumentAttachment, ...],
) -> tuple[str | None, tuple[ImageAttachment, ...]]:
    # #261102: the Claw turn keeps the one Chat attachment boundary — every
    # attached document rides the same per-file context builder, so no file
    # is silently dropped when several are attached.
    documents = tuple(item for item in attachments if isinstance(item, DocumentAttachment))
    images = tuple(item for item in attachments if isinstance(item, ImageAttachment))
    context = build_documents_context(documents)
    return context, images


def parse_claw_turn_attachments(
    raw: Any,
) -> tuple[str | None, tuple[ImageAttachment, ...]]:
    """Read one attached file with the Chat contract.

    Returns the shared document reference context (``None`` when no document was
    attached) plus every image the caller attached, so the route can refuse an
    image before any quota, Engine dispatch or provider call. Raises
    ``AttachmentValidationError`` exactly where Chat raises it, with the same
    message.
    """
    return _project_attachments(parse_attachments(raw))


async def parse_claw_turn_attachments_async(
    raw: Any, *, file_resolver=None,
) -> tuple[str | None, tuple[ImageAttachment, ...]]:
    """Worker request path for the Claw turn attachment contract."""

    return _project_attachments(await parse_attachments_async(raw, file_resolver=file_resolver))


__all__ = [
    "CLAW_IMAGE_ATTACHMENT_UNSUPPORTED",
    "AttachmentValidationError",
    "parse_claw_turn_attachments",
    "parse_claw_turn_attachments_async",
]
