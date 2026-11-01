"""Chat-owned COM2 tickets and owner-scoped parsed-text references (#5881).

Only the deployment-configured HTTPS origin is used. Browser file IDs never
select an origin, path, user ID, or authentication secret. Original bytes go
browser -> COM2; Chat reads only small metadata and the extracted text.
"""
from __future__ import annotations

import base64
import json
import re
import time

import httpx
from starlette.responses import JSONResponse

from .attachments import AttachmentValidationError
from .auth_routes import auth_ready, current_user_id
from .b14_service_proof import service_proof_headers
from .binary_documents import guidance_for_reason_code
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .documents import DocumentAttachment, _safe_name, _validate_text
from .config import _normalize_base_url

FILE_ID = re.compile(r"file_[a-f0-9]{32}\Z")
KINDS = {
    "txt": "text/plain", "md": "text/markdown", "csv": "text/csv", "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "hwpx": "application/hwp+zip",
}
BINARY_KINDS = frozenset({"pdf", "docx", "pptx", "xlsx", "hwpx"})
TICKET_LIFETIME_SECONDS = 600

# The constant reason codes the lane may answer a text read with (#6338): the
# Core document_normalization refusal catalog the lane's own allowlist draws
# from. Only a code crosses here — a lane error body's other content, like any
# parser exception text, never reaches the owner.
REASON_CODES = frozenset({
    "ooxml_archive_size", "ooxml_encrypted", "ooxml_unsafe_path", "ooxml_link_entry",
    "ooxml_dtd_rejected", "ooxml_entry_size", "ooxml_total_inflation", "ooxml_malformed",
    "ooxml_invalid_xml",
    "docx_missing_part", "docx_empty", "pptx_missing_slides", "pptx_empty",
    "xlsx_invalid", "xlsx_no_sheets", "xlsx_empty",
    "hwpx_missing_part", "hwpx_empty", "hwpx_mimetype_mismatch",
    "pdf_magic_mismatch", "pdf_encrypted", "pdf_invalid", "pdf_no_pages",
    "pdf_empty_text", "pdf_page_text_invalid", "pdf_page_geometry_unavailable",
    "empty_document", "binary_text_rejected", "excessive_control_characters", "invalid_text",
    "document_dependency_unavailable",
})
_UNREADABLE_TEXT = "첨부 문서의 텍스트를 읽지 못했습니다."


async def _lane_refusal_message(response, media_type: str) -> str:
    """Per-code guidance from the lane's ``{"ok": false, "error": {"code": ...}}``.

    The body is parsed defensively and only its constant reason code is used:
    anything unmapped, malformed, or unreadable keeps the generic wording.
    """

    try:
        body = json.loads(await response.aread())
        code = body["error"]["code"] if isinstance(body, dict) else None
    except Exception:
        code = None
    if isinstance(code, str) and code in REASON_CODES:
        return guidance_for_reason_code(code, media_type) or _UNREADABLE_TEXT
    return _UNREADABLE_TEXT


def ticket_headers(secret, user_id, maximum):
    expires = int(time.time()) + TICKET_LIFETIME_SECONDS
    raw = json.dumps({"user_id": user_id, "max_bytes": maximum, "expires": expires}, separators=(",", ":")).encode()
    proof = service_proof_headers(secret, raw)
    if not proof:
        raise AttachmentValidationError("파일 서버가 아직 연결되지 않았습니다.")
    return {"X-Padiem-File-Ticket": base64.urlsafe_b64encode(raw).rstrip(b"=").decode(),
            "X-Padiem-File-Time": proof["X-Padiem-B14-Time"],
            "X-Padiem-File-Proof": proof["X-Padiem-B14-Proof"]}, expires


class _LaneRawStream:
    """One streamed lane response; iterating never materializes the whole file."""

    def __init__(self, url, *, headers, transport):
        self._url = url
        self._headers = headers
        self._transport = transport
        self._client = None
        self._context = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            transport=self._transport, timeout=None,
            follow_redirects=False, trust_env=False,
        )
        self._context = self._client.stream("GET", self._url, headers=self._headers)
        try:
            return await self._context.__aenter__()
        except Exception:
            await self.__aexit__(None, None, None)
            raise AttachmentValidationError("파일 서버에서 원본을 가져오지 못했습니다.") from None

    async def __aexit__(self, *exc_info):
        try:
            if self._context is not None:
                await self._context.__aexit__(*exc_info)
        finally:
            if self._client is not None:
                await self._client.aclose()


class FileLaneClient:
    def __init__(self, origin, secret, *, transport=None):
        self.origin = _normalize_base_url(origin, https_only=True, root_only=True) if origin else None
        self._secret, self._transport = secret, transport

    @property
    def ready(self):
        return bool(self.origin and self._secret and len(self._secret) >= 32)

    def upload_ticket(self, user_id, maximum):
        if not self.ready:
            raise AttachmentValidationError("파일 서버가 아직 연결되지 않았습니다.")
        headers, expires = ticket_headers(self._secret, user_id, maximum)
        return {"ok": True, "upload_url": self.origin + "/files", "headers": headers,
                "expires": expires, "max_bytes": maximum}

    def read_ticket(self, user_id):
        """One fresh read capability for the server-verified current owner.

        max_bytes is an upload budget, not permission to another namespace, so
        every read mints the same minimal claim. #5881 stage 4 hands that claim
        to the Engine instead of using it here, and both paths keep this single
        mint point so no second ticket authority appears.
        """
        if not self.ready:
            raise AttachmentValidationError("파일 서버가 아직 연결되지 않았습니다.")
        return ticket_headers(self._secret, user_id, 1)

    async def meta(self, user_id, file_id):
        """Small metadata for one uploaded file; never the file body."""
        if (not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id)):
            raise AttachmentValidationError("첨부 파일 참조 형식이 올바르지 않습니다.")
        if not self.ready:
            raise AttachmentValidationError("파일 서버가 아직 연결되지 않았습니다.")
        headers, _ = self.read_ticket(user_id)
        url = self.origin + "/files/" + file_id + "/meta"
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=None, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        raise AttachmentValidationError("첨부 파일을 찾을 수 없거나 읽을 권한이 없습니다.")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 16 * 1024:  # Metadata only; never a file/text ceiling.
                            raise ValueError("invalid metadata")
                    meta = json.loads(raw)
        except AttachmentValidationError:
            raise
        except Exception:
            raise AttachmentValidationError("첨부 문서를 현재 읽을 수 없습니다.") from None
        if (not isinstance(meta, dict) or meta.get("file_id") != file_id
                or meta.get("kind") not in KINDS or type(meta.get("size_bytes")) is not int
                or meta["size_bytes"] <= 0 or not isinstance(meta.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", meta["sha256"])):
            raise AttachmentValidationError("첨부 문서를 현재 읽을 수 없습니다.")
        return meta

    def open_raw(self, user_id, file_id):
        """One streamed original; the caller iterates, this module never buffers.

        Returns an async context manager whose ``__aenter__`` is the lane's
        response so the caller can answer a lane refusal before streaming.
        """
        if not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id):
            raise AttachmentValidationError("첨부 파일 참조 형식이 올바르지 않습니다.")
        if not self.ready:
            raise AttachmentValidationError("파일 서버가 아직 연결되지 않았습니다.")
        headers, _ = self.read_ticket(user_id)
        return _LaneRawStream(self.origin + "/files/" + file_id + "/raw",
                              headers=headers, transport=self._transport)

    async def resolve(self, user_id, item):
        if (not isinstance(item, dict) or set(item) != {"type", "file_id"}
                or item.get("type") != "file" or not isinstance(item.get("file_id"), str)
                or not FILE_ID.fullmatch(item["file_id"])):
            raise AttachmentValidationError("첨부 파일 참조 형식이 올바르지 않습니다.")
        if not self.ready:
            raise AttachmentValidationError("파일 서버가 아직 연결되지 않았습니다.")
        meta = await self.meta(user_id, item["file_id"])
        headers, _ = self.read_ticket(user_id)
        url = self.origin + "/files/" + item["file_id"]
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=None, follow_redirects=False, trust_env=False) as client:
                name = _safe_name(meta.get("name"))
                async with client.stream("GET", url + "/text", headers=headers) as response:
                    if response.status_code != 200:
                        raise AttachmentValidationError(
                            await _lane_refusal_message(response, KINDS[meta["kind"]]))
                    # COM2 owns parsing. No original PDF/ZIP/image is fetched or
                    # decoded in the Worker; this is the model's text context.
                    text = "".join([part async for part in response.aiter_text()])
            return DocumentAttachment(name=name, media_type=KINDS[meta["kind"]],
                text=_validate_text(text), byte_size=meta["size_bytes"], file_id=item["file_id"],
                sha256=meta["sha256"])
        except AttachmentValidationError:
            raise
        except Exception:
            # Transport/parser exception text may contain headers or documents.
            raise AttachmentValidationError("첨부 문서를 현재 읽을 수 없습니다.") from None


async def owner(request):
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    if not uid or store is None:
        return None
    try:
        return uid if await store.get_user(uid) is not None else None
    except Exception:
        return None


def file_resolver(request):
    async def resolve(item):
        uid = await owner(request)
        if not uid:
            raise AttachmentValidationError("파일 첨부를 사용하려면 로그인이 필요합니다.")
        # #6579 step 3: an attachment uploaded through this app's own resumable
        # lane lives in the workspace bucket under the owner's key. It is
        # answered here — the browser grammar, the parser authority and the
        # model contract are all unchanged — and anything else falls through to
        # the untouched COM2 lane. A foreign id is simply not found locally, so
        # it gets the lane's own not-found answer.
        from .tus_chat_attachment import chat_attachment_store

        store = chat_attachment_store(request)
        if store is not None and isinstance(item, dict) and isinstance(item.get("file_id"), str):
            local = await store.resolve(uid, item["file_id"])
            if local is not None:
                return local
        client = request.app.state.file_lane_client
        return await client.resolve(uid, item)
    return resolve


async def file_upload_ticket(request):
    uid = await owner(request)
    if not uid:
        return failure("unauthorized", "파일 업로드를 사용하려면 로그인이 필요합니다.", 401)
    client = request.app.state.file_lane_client
    if not client.ready:
        return failure("file_lane_unavailable", "파일 서버가 아직 연결되지 않았습니다.", 503)
    try:
        raw = json.loads(await read_bounded_request_body(request, max_bytes=2048))
        if (not isinstance(raw, dict) or set(raw) != {"size_bytes"}
                or type(raw["size_bytes"]) is not int or not 0 < raw["size_bytes"] <= 2**53 - 1):
            raise ValueError("invalid size")
    except RequestBodyTooLarge:
        return failure("invalid_request", "업로드 티켓 요청이 올바르지 않습니다.", 413)
    except (ValueError, UnicodeError):
        return failure("invalid_request", "업로드 티켓 요청이 올바르지 않습니다.", 422)
    return JSONResponse(client.upload_ticket(uid, raw["size_bytes"]), headers={"Cache-Control": "no-store"})


def failure(code, message, status):
    return JSONResponse({"ok": False, "error": {"code": code, "message": message}},
                        status_code=status, headers={"Cache-Control": "no-store"})


async def file_capabilities(request):
    from .attachments import max_attachments_per_message

    ready = bool(await owner(request)) and request.app.state.file_lane_client.ready
    return JSONResponse({"ready": ready, "auto_bytes": 10_000_000, "formats": list(KINDS),
                        "max_per_message": max_attachments_per_message()},
                        headers={"Cache-Control": "no-store"})
