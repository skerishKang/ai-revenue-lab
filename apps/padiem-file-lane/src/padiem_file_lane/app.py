"""Local plain-HTTP ASGI service, intended only behind Cloudflare Tunnel."""
from __future__ import annotations

import os
from pathlib import Path

import anyio
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .storage import FileError, Store, disk_error, require_space
from .tickets import InvalidTicket, verify_ticket


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
        return JSONResponse({"ok": True, **meta}, headers={"Cache-Control": "no-store"})

    async def text(request: Request):
        claims = ticket(request)
        path = await run_in_threadpool(store.text, claims.user_id, request.path_params["file_id"])
        return FileResponse(path, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})

    async def health(request):
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    async def denied(request, exc):
        return error("invalid_ticket", 401)

    async def failed(request, exc):
        return error(exc.code, exc.status)

    async def disk_failed(request, exc):
        failure = disk_error(exc)
        return error(failure.code, failure.status)

    app = Starlette(routes=[Route("/health", health), Route("/files", upload, methods=["POST"]),
                            Route("/files/{file_id}/meta", metadata), Route("/files/{file_id}/text", text)],
                    exception_handlers={InvalidTicket: denied, FileError: failed, OSError: disk_failed})
    app.state.store = store
    allowed = origins if origins is not None else [x.strip() for x in os.environ.get("FILE_LANE_ALLOWED_ORIGINS", "").split(",") if x.strip()]
    if "*" in allowed:
        raise RuntimeError("FILE_LANE_ALLOWED_ORIGINS must name explicit Chat origins")
    if allowed:
        app.add_middleware(CORSMiddleware, allow_origins=allowed, allow_credentials=True, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-Padiem-File-Ticket", "X-Padiem-File-Time", "X-Padiem-File-Proof"])
    return app


def error(code, status):
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status,
                        headers={"Cache-Control": "no-store"})
