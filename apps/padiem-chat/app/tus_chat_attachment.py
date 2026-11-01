"""Chat attachment lane over the shared tus core (#6579 → 1GB step 3).

A Chat attachment used to travel as base64 inside the conversation request,
which the Cloudflare free-plan 100 MB request limit caps at ~75 MB of real
file. This lane removes that ceiling the same way the project and web-XLSX
lanes did: the protocol lives in ``app/tus_core.py`` and is reused here, not
copied. Only what is genuinely this lane's own is supplied:

* the owner scope is the signed-in account (``file_lane.owner``: session cookie
  plus an existing user row);
* the accepted types are the Chat attachment document vocabulary
  (``file_lane.KINDS``), so an upload that this lane accepts is one the
  existing resolver can already read;
* completion streams the assembled chunk file into the workspace object store
  (``put_stream``: a move on the same filesystem, bounded blocks otherwise) and
  answers with an unguessable reference id.

The conversation request keeps its exact grammar: the browser sends
``{"type": "file", "file_id": ...}`` and ``file_lane.file_resolver`` answers
it. Objects live under ``chat-attachments/<owner>/<id>/`` only, and the
metadata carries the owner, so another account's id resolves to nothing and
falls through to the untouched COM2 lane answer (not found).

Why the scope is the account and not the conversation: an attachment is
uploaded *before* the turn that uses it, so for a brand-new chat there is no
conversation id yet. Binding the upload to a conversation would mean either
inventing one at upload time or weakening the check; the conversation link
belongs to the turn, and the per-account key namespace is what actually
isolates owners. ``conversation_id`` is therefore recorded as a hint only.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import secrets
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from .attachments import AttachmentValidationError
from .binary_documents import BinaryDocumentValidationError, parse_binary_document_item_async
from .documents import DocumentAttachment, _validate_text
from .file_lane import KINDS, owner
from .local_r2 import put_stream
from .tus_core import TusLane, error, max_upload_bytes, tus_creation, tus_resource

LANE_NAME = "chat_attachment"
CHAT_ATTACHMENT_TUS_COLLECTION_PATH = "/api/chat/attachments/tus"
CHAT_ATTACHMENT_TUS_ITEM_PATH = "/api/chat/attachments/tus/{upload_id}"
ATTACHMENT_ROOT = "chat-attachments"

# The same id shape the Chat grammar already carries (`file_lane.FILE_ID`), so
# nothing in the browser contract has to change to use a locally stored
# attachment. The body is 16 random bytes: guessing one is not a plan.
ATTACHMENT_ID = re.compile(r"file_[a-f0-9]{32}\Z")

_TEXT_MEDIA = frozenset({KINDS["txt"], KINDS["md"], KINDS["csv"]})
_BINARY_MEDIA = frozenset({KINDS["pdf"], KINDS["docx"], KINDS["pptx"], KINDS["xlsx"]})
ACCEPTED_MEDIA = _TEXT_MEDIA | _BINARY_MEDIA

INVALID_TYPE_MESSAGE = (
    "TXT, Markdown, CSV, PDF, DOCX, PPTX, XLSX 문서만 첨부할 수 있습니다."
)
NOT_FOUND_MESSAGE = "첨부를 찾을 수 없습니다."


def _safe_segment(value: Any) -> str:
    """One owner segment of a key: a plain identifier, never a path."""

    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or value in (".", "..")
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise ValueError("chat attachment scope is not a plain identifier")
    return value


def _base_key(user_id: str, attachment_id: str) -> str:
    return f"{ATTACHMENT_ROOT}/{_safe_segment(user_id)}/{attachment_id}"


async def _awaitable(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class ChatAttachmentStore:
    """Bounded-block writes and owner-scoped reads for Chat attachments.

    The object store is the workspace bucket the rest of Chat already uses. No
    bytes are held whole on the way in: the completed chunk file is handed to
    ``put_stream``, and only the small metadata JSON is written as bytes.
    """

    def __init__(self, bucket: Any):
        if bucket is None:
            raise ValueError("attachment object store is required")
        self.r2_bucket = bucket

    async def _put_bytes(self, key: str, body: bytes, content_type: str) -> None:
        await _awaitable(self.r2_bucket.put(key, body, {"contentType": content_type}))

    async def _get_bytes(self, key: str) -> bytes | None:
        obj = await _awaitable(self.r2_bucket.get(key))
        if obj is None:
            return None
        body = getattr(obj, "body", None)
        if body is None:
            return None
        return bytes(body)

    async def save(self, *, user_id: str, name: str, media_type: str,
                   source_path: Any, conversation_id: str | None = None) -> dict[str, Any]:
        """Stream one assembled upload into the store and return its reference."""

        path = Path(source_path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValueError("chat attachment source is missing") from exc
        if not 0 < size <= max_upload_bytes():
            raise ValueError("chat attachment exceeds upload limit")
        if media_type not in ACCEPTED_MEDIA:
            raise ValueError("chat attachment type is not accepted")
        # Hash in bounded blocks so the digest never depends on the file size.
        digest = hashlib.sha256()
        with path.open("rb") as reader:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                digest.update(block)
        attachment_id = "file_" + secrets.token_hex(16)
        base = _base_key(user_id, attachment_id)
        written = put_stream(self.r2_bucket, base + "/body", path,
                             {"contentType": media_type})
        await _awaitable(written)
        meta = {
            "attachment_id": attachment_id,
            "user_id": _safe_segment(user_id),
            "name": name,
            "media_type": media_type,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
            "conversation_id": conversation_id,
        }
        await self._put_bytes(base + "/meta.json",
                              json.dumps(meta, ensure_ascii=False).encode("utf-8"),
                              "application/json")
        return meta

    async def resolve(self, user_id: str, attachment_id: str) -> DocumentAttachment | None:
        """Read one attachment back as the model's document context.

        ``None`` for anything that is not this owner's attachment, so a foreign
        id behaves exactly like an unknown one instead of answering 403.
        """

        if not isinstance(attachment_id, str) or not ATTACHMENT_ID.fullmatch(attachment_id):
            return None
        try:
            segment = _safe_segment(user_id)
            base = _base_key(segment, attachment_id)
        except ValueError:
            return None
        raw = await self._get_bytes(base + "/meta.json")
        if raw is None:
            return None
        try:
            meta = json.loads(raw)
        except ValueError:
            return None
        if (not isinstance(meta, dict) or meta.get("attachment_id") != attachment_id
                or meta.get("user_id") != segment
                or meta.get("media_type") not in ACCEPTED_MEDIA):
            return None
        body = await self._get_bytes(base + "/body")
        if body is None:
            return None
        name = str(meta.get("name") or "")
        media_type = str(meta["media_type"])
        sha256 = meta.get("sha256")
        if media_type in _TEXT_MEDIA:
            try:
                text = _validate_text(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise AttachmentValidationError(
                    "문서에서 추출한 텍스트를 사용할 수 없습니다.") from exc
            return DocumentAttachment(name=name, media_type=media_type, text=text,
                                      byte_size=len(body), file_id=attachment_id,
                                      sha256=sha256)
        # Binary documents keep the one existing parser authority and its
        # per-code wording; this lane adds no second parse path.
        try:
            parsed = await parse_binary_document_item_async({
                "type": "document", "name": name,
                "media_type": media_type, "raw_bytes": body,
            })
        except BinaryDocumentValidationError as exc:
            raise AttachmentValidationError(str(exc)) from exc
        return DocumentAttachment(
            name=parsed.name, media_type=parsed.media_type, text=parsed.text,
            byte_size=parsed.byte_size, segments=parsed.segments,
            file_id=attachment_id, sha256=sha256,
        )


def chat_attachment_store(request: Request) -> ChatAttachmentStore | None:
    """The lane's store, bound lazily from the existing workspace bucket."""

    existing = getattr(request.app.state, "chat_attachment_store", None)
    if existing is not None:
        return existing
    workspace = getattr(request.app.state, "workspace_document_store", None)
    bucket = getattr(workspace, "r2_bucket", None)
    if bucket is None:
        return None
    store = ChatAttachmentStore(bucket)
    try:
        request.app.state.chat_attachment_store = store
    except Exception:
        return store
    return store


def _unavailable() -> dict[str, Any]:
    return {"status": 503, "body": {"ok": False, "error": {
        "code": "chat_attachment_unavailable",
        "message": "첨부 파일을 현재 저장할 수 없습니다."}}}


async def _identity(request: Request):
    account = await owner(request)
    if not account:
        return None, error(401, "unauthorized", "파일 첨부를 사용하려면 로그인이 필요합니다.")
    if chat_attachment_store(request) is None:
        return None, error(503, "chat_attachment_unavailable",
                           "첨부 파일을 현재 저장할 수 없습니다.")
    return {"user_id": account}, None


def _location(request: Request, meta: dict) -> str:
    return f"/api/chat/attachments/tus/{meta['upload_id']}"


async def _finalize(request: Request, data_path: str, meta: dict) -> dict[str, Any]:
    store = chat_attachment_store(request)
    if store is None:
        return _unavailable()
    try:
        saved = await store.save(
            user_id=str(meta["scope"]["user_id"]),
            name=str(meta["filename"]),
            media_type=str(meta["media_type"]),
            source_path=data_path,
        )
    except ValueError:
        return {"status": 422, "body": {"ok": False, "error": {
            "code": "invalid_document", "message": INVALID_TYPE_MESSAGE}}}
    except Exception:
        return _unavailable()
    return {"status": 201, "body": {"ok": True, "file": {
        "file_id": saved["attachment_id"],
        "name": saved["name"],
        "media_type": saved["media_type"],
        "size_bytes": saved["size_bytes"],
        "sha256": saved["sha256"],
    }}}


def chat_attachment_lane() -> TusLane:
    return TusLane(
        name=LANE_NAME,
        identity=_identity,
        finalize=_finalize,
        accepts=lambda media_type: media_type in ACCEPTED_MEDIA,
        location=_location,
        max_upload_bytes=max_upload_bytes,
        invalid_type_message=INVALID_TYPE_MESSAGE,
        not_found_message=NOT_FOUND_MESSAGE,
        unavailable_code="chat_attachment_unavailable",
        unavailable_message="첨부 파일을 현재 저장할 수 없습니다.",
    )


async def chat_attachment_tus_collection(request: Request) -> Response:
    """tus creation (POST) and capability discovery (OPTIONS)."""

    return await tus_creation(request, chat_attachment_lane())


async def chat_attachment_tus_item(request: Request) -> Response:
    """tus status (HEAD), append (PATCH) and one-time result pickup (GET)."""

    return await tus_resource(request, chat_attachment_lane())


__all__ = [
    "ACCEPTED_MEDIA",
    "ATTACHMENT_ID",
    "ATTACHMENT_ROOT",
    "CHAT_ATTACHMENT_TUS_COLLECTION_PATH",
    "CHAT_ATTACHMENT_TUS_ITEM_PATH",
    "ChatAttachmentStore",
    "LANE_NAME",
    "chat_attachment_lane",
    "chat_attachment_store",
    "chat_attachment_tus_collection",
    "chat_attachment_tus_item",
]
