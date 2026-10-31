"""Local plain-HTTP ASGI service, intended only behind Cloudflare Tunnel."""
from __future__ import annotations

import os
from pathlib import Path

import anyio
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from .storage import FileError, Store, disk_error, require_space
from .journal import RequestJournal, RequestJournalMiddleware, row_from_scope
from . import xlsx_edit
from . import hwp_text
from .tickets import InvalidTicket, verify_ticket

_MEDIA_BY_KIND = {
    "txt": "text/plain; charset=utf-8", "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8", "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def create_app(*, root: Path | None = None, secret: str | None = None, origins=None):
    if root is None:
        configured = os.environ.get("FILE_LANE_ROOT", "")
        if not configured:
            raise RuntimeError("FILE_LANE_ROOT is required")
        root = Path(configured)
    if not root.is_absolute():
        raise RuntimeError("FILE_LANE_ROOT must be absolute")
    secret = secret if secret is not None else os.environ.get("FILE_LANE_TICKET_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("FILE_LANE_TICKET_SECRET must contain at least 32 characters")
    store = Store(root)
    journal = RequestJournal(root)

    def mark(request, *, code=None, size=None):
        """Place a constant error code or byte count on the request's journal
        row. Names, content, tickets and exception text never go through here."""
        row = row_from_scope(request.scope)
        if code is not None:
            row["error_code"] = code
        if size is not None:
            row["file_size"] = size

    def _xlsx_source(store, user_id, file_id):
        meta = store.meta(user_id, file_id)
        if meta.get("kind") != "xlsx":
            raise FileError("unsupported_file_type", 415)
        directory = store.directory(user_id, file_id)
        return (directory / "data").read_bytes(), meta

    def ticket(request):
        return verify_ticket(request.headers, secret)

    async def upload(request: Request):
        claims = ticket(request)
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdigit():
                raise FileError("invalid_content_length", 400)
            length = int(length)
            if length > claims.max_bytes:
                raise FileError("ticket_size_exceeded", 413)
            await run_in_threadpool(require_space, store.root, length)
        pending = await run_in_threadpool(store.new_upload, claims.user_id, request.query_params.get("filename", ""))
        try:
            await run_in_threadpool(pending.open)
            # Raw request chunks go straight to disk, never request.body() or
            # multipart/base64 buffers. Chunked uploads have the same checks.
            async for block in request.stream():
                if block:
                    await run_in_threadpool(pending.write, block, claims.max_bytes)
            if length is not None and pending.size != length:
                raise FileError("content_length_mismatch", 400)
            meta = await run_in_threadpool(pending.finish)
            mark(request, size=meta["size_bytes"])
            return JSONResponse({"ok": True, **meta}, status_code=201, headers={"Cache-Control": "no-store"})
        except ClientDisconnect:
            raise FileError("upload_interrupted", 400) from None
        finally:
            # Even a disconnected/cancelled upload must close its handle before
            # deleting partial data (also required by Windows file semantics).
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(pending.close)

    async def metadata(request: Request):
        claims = ticket(request)
        meta = await run_in_threadpool(store.meta, claims.user_id, request.path_params["file_id"])
        mark(request, size=meta["size_bytes"])
        return JSONResponse({"ok": True, **meta}, headers={"Cache-Control": "no-store"})

    async def text(request: Request):
        claims = ticket(request)
        window = any(key in request.query_params for key in ("offset", "max_chars"))
        bounds = []
        for key, default, minimum in (("offset", "0", 0), ("max_chars", "64000", 1)):
            raw = request.query_params.get(key, default)
            try:
                if not raw.isascii() or not raw.isdigit():
                    raise ValueError
                value = int(raw)
                if value < minimum:
                    raise ValueError
            except ValueError:
                raise FileError("invalid_text_window", 400) from None
            bounds.append(value)
        path = await run_in_threadpool(store.text, claims.user_id, request.path_params["file_id"])
        mark(request, size=path.stat().st_size)
        if window:
            offset, max_chars = bounds
            content, eof = await run_in_threadpool(store.text_window, path, offset, max_chars)
            total = await run_in_threadpool(store.text_char_count, path)
            return PlainTextResponse(content, headers={"Cache-Control": "no-store",
                "X-File-Lane-Next-Offset": str(offset + len(content)), "X-File-Lane-EOF": str(eof).lower(),
                "X-File-Lane-Total-Chars": str(total)})
        return FileResponse(path, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})

    async def structure(request):
        claims = ticket(request)
        data, meta = await run_in_threadpool(_xlsx_source, store, claims.user_id,
                                             request.path_params["file_id"])
        mark(request, size=meta["size_bytes"])
        form = await run_in_threadpool(xlsx_edit.describe, data)
        return JSONResponse({"ok": True, "file_id": meta["file_id"], "name": meta["name"],
                             **form}, headers={"Cache-Control": "no-store"})

    async def fill(request):
        claims = ticket(request)
        try:
            body = await request.json()
        except Exception:
            raise FileError("invalid_body", 400) from None
        if not isinstance(body, dict) or set(body) - {"mapping", "extend", "filename"}:
            raise FileError("invalid_body", 400)
        data, _meta = await run_in_threadpool(_xlsx_source, store, claims.user_id,
                                              request.path_params["file_id"])
        try:
            filled = await run_in_threadpool(
                xlsx_edit.fill, data,
                mapping=body.get("mapping"), extensions=body.get("extend"),
            )
        except xlsx_edit.FormError as exc:
            raise FileError(exc.code, 422) from None
        name = body.get("filename") or "filled.xlsx"
        pending = store.new_upload(claims.user_id, name)
        try:
            await run_in_threadpool(pending.open)
            await run_in_threadpool(pending.write, filled, claims.max_bytes)
            meta = await run_in_threadpool(pending.finish)
            mark(request, size=meta["size_bytes"])
        finally:
            with anyio.CancelScope(shield=True):
                if not pending.committed:
                    await run_in_threadpool(pending.close)
        return JSONResponse({"ok": True, **meta}, status_code=201,
                            headers={"Cache-Control": "no-store"})

    async def raw(request):
        claims = ticket(request)
        directory = await run_in_threadpool(store.directory, claims.user_id,
                                            request.path_params["file_id"])
        meta = await run_in_threadpool(store.meta, claims.user_id,
                                       request.path_params["file_id"])
        mark(request, size=meta["size_bytes"])
        media = _MEDIA_BY_KIND.get(meta.get("kind"), "application/octet-stream")
        return FileResponse(directory / "data", media_type=media,
                            filename=meta["name"], headers={"Cache-Control": "no-store"})

    async def hwp_reference(request: Request):
        # #5895: the legacy .hwp reader lives here, where olefile (BSD) runs —
        # the Worker hands the bytes over and gets the words back. The body is
        # capped by the same upload ticket every write uses.
        claims = ticket(request)
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdigit():
                raise FileError("invalid_content_length", 400)
            if int(length) > claims.max_bytes:
                raise FileError("ticket_size_exceeded", 413)
        received = 0
        chunks = []
        async for block in request.stream():
            received += len(block)
            if received > claims.max_bytes:
                raise FileError("ticket_size_exceeded", 413)
            chunks.append(block)
        try:
            text = await run_in_threadpool(hwp_text.extract_text, b"".join(chunks))
        except hwp_text.HwpError as exc:
            raise FileError(exc.code, 422) from None
        mark(request, size=received)
        return JSONResponse({"ok": True, "text": text, "chars": len(text)},
                            headers={"Cache-Control": "no-store"})

    async def health(request):
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    async def denied(request, exc):
        mark(request, code="invalid_ticket")
        return error("invalid_ticket", 401)

    async def failed(request, exc):
        mark(request, code=exc.code)
        return error(exc.code, exc.status)

    async def disk_failed(request, exc):
        failure = disk_error(exc)
        mark(request, code=failure.code)
        return error(failure.code, failure.status)

    app = Starlette(routes=[Route("/health", health), Route("/files", upload, methods=["POST"]),
                            Route("/files/{file_id}/meta", metadata), Route("/files/{file_id}/text", text),
                            Route("/files/{file_id}/structure", structure),
                            Route("/files/{file_id}/fill", fill, methods=["POST"]),
                            Route("/files/{file_id}/raw", raw),
                            Route("/files/hwp-text", hwp_reference, methods=["POST"])],
                    exception_handlers={InvalidTicket: denied, FileError: failed, OSError: disk_failed})
    app.state.store = store
    app.state.journal = journal
    app.add_middleware(RequestJournalMiddleware, journal=journal)
    allowed = origins if origins is not None else [x.strip() for x in os.environ.get("FILE_LANE_ALLOWED_ORIGINS", "").split(",") if x.strip()]
    if "*" in allowed:
        raise RuntimeError("FILE_LANE_ALLOWED_ORIGINS must name explicit Chat origins")
    if allowed:
        app.add_middleware(CORSMiddleware, allow_origins=allowed, allow_credentials=True, allow_methods=["GET", "POST"],
                           expose_headers=["X-File-Lane-Next-Offset", "X-File-Lane-EOF",
                                           "X-File-Lane-Total-Chars"],
                           allow_headers=["Content-Type", "X-Padiem-File-Ticket", "X-Padiem-File-Time", "X-Padiem-File-Proof"])
    return app


def error(code, status):
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status,
                        headers={"Cache-Control": "no-store"})
