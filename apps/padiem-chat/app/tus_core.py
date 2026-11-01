"""tus 1.0.0 core shared by every resumable upload lane (#6579 → 1GB step 2).

#6579 put the protocol in the project-file lane. The Owner's decision for
step 2 is that the web XLSX and Chat-attachment lanes must **reuse** it, not
copy it, so the verbs live here once and each lane supplies only what is truly
its own:

    create    which owner scope a new upload belongs to, and which media/types
              that lane accepts (and its own size ceiling, if smaller);
    finalize  what a completed upload becomes in that lane's existing flow.

Everything else is identical for every lane and is owned by this module: the
three protocol verbs, the offset arithmetic that makes a retried chunk safe, the
configurable ceilings, the temporary chunk directory, the unguessable upload id,
the opportunistic sweep, and the rule that another user's upload behaves exactly
like a missing one.

Design decisions kept verbatim from the design doc (A안):

- Chunks stay under the Cloudflare free-plan request-body limit: the per-PATCH
  ceiling defaults to 90 MiB (PADIEM_TUS_CHUNK_MAX_BYTES).
- The total ceiling defaults to 1 GiB (PADIEM_TUS_MAX_UPLOAD_BYTES); a lane may
  declare a smaller one and the browser learns it from this endpoint, so no lane
  keeps its own constant.
- Temporary chunk files live in the systemd-writable data path only
  (11-01 운영 교훈 8-1): PADIEM_TUS_UPLOAD_DIR, or under
  PADIEM_CHAT_LOCAL_DATA_DIR when set, or the private temp dir. Never on /mnt/d.
- Upload ids are unguessable (secrets.token_urlsafe) and every request is
  re-checked against the signed-in owner's scope, so another user's upload URL
  behaves exactly like a missing one (404).
- Incomplete uploads are swept after PADIEM_TUS_CLEANUP_SECONDS (default 24h);
  the sweep runs opportunistically on every creation.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import secrets
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .bounded_request_body import RequestBodyTooLarge, open_bounded_spooled_request

TUS_VERSION = "1.0.0"
TUS_CONTENT_TYPE = "application/offset+octet-stream"
_META_NAME = "upload.json"
_DATA_NAME = "data.bin"

DEFAULT_CHUNK_MAX_BYTES = 90 * 1024 * 1024
DEFAULT_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


def _int_setting(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw or not raw.isdecimal():
        return default
    return int(raw)


def chunk_max_bytes() -> int:
    return _int_setting("PADIEM_TUS_CHUNK_MAX_BYTES", DEFAULT_CHUNK_MAX_BYTES)


def max_upload_bytes() -> int:
    return _int_setting("PADIEM_TUS_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)


def cleanup_seconds() -> int:
    return _int_setting("PADIEM_TUS_CLEANUP_SECONDS", 86400)


def upload_root() -> str:
    configured = (os.environ.get("PADIEM_TUS_UPLOAD_DIR") or "").strip()
    if configured:
        return configured
    data_dir = (os.environ.get("PADIEM_CHAT_LOCAL_DATA_DIR") or "").strip()
    if data_dir:
        return os.path.join(data_dir, "tus-uploads")
    # The service runs with PrivateTmp, so the system temp dir is a writable
    # per-service path even under ProtectSystem=strict (11-01 lesson 8-1).
    return os.path.join(tempfile.gettempdir(), "padiem-tus-uploads")


def human_bytes(total: int) -> str:
    value = float(total)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.0f}{unit}"
        value /= 1024
    return f"{value / 1024:.1f}GB"


def tus_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    headers = {"Tus-Resumable": TUS_VERSION, "Cache-Control": "no-store"}
    if extra:
        headers.update(extra)
    return headers


def error(status: int, code: str, message: str,
          headers: Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}},
                        status_code=status, headers=tus_headers(headers))


@dataclass(frozen=True)
class TusLane:
    """What one lane has to supply; everything else is this module's own job.

    ``identity`` returns either ``(scope, None)`` or ``(None, response)``. The
    scope is a closed dict of the keys that bind an upload to its owner and
    place — for a project ``{"user_id", "project_id"}``, for a chat attachment
    ``{"user_id", "workspace_id"}``. Ownership is exact equality of that dict,
    so a lane cannot invent a weaker check.

    ``finalize`` receives the completed chunk file path plus the stored meta and
    returns ``{"status": int, "body": Any}``: the same shape ``tus_project_upload``
    already stored and served back on the one-time GET.
    """

    name: str
    identity: Callable[[Request], Awaitable[tuple[dict[str, Any] | None, Response | None]]]
    finalize: Callable[[Request, str, dict[str, Any]], Awaitable[dict[str, Any]]]
    accepts: Callable[[str], bool]
    location: Callable[[Request, dict[str, Any]], str]
    max_upload_bytes: Callable[[], int] = max_upload_bytes
    invalid_type_message: str = "이 형식으로는 올릴 수 없습니다."
    not_found_message: str = "업로드를 찾을 수 없습니다."
    unavailable_status: int = 503
    unavailable_code: str = "upload_unavailable"
    unavailable_message: str = "업로드를 현재 사용할 수 없습니다."


def _meta_path(upload_id: str) -> str:
    return os.path.join(upload_root(), upload_id, _META_NAME)


def _load_meta(upload_id: str) -> dict | None:
    # upload_id comes from the URL; reject anything that is not a plain token
    # so the lookup can never escape the upload root.
    if not upload_id or "/" in upload_id or "\\" in upload_id or upload_id in (".", ".."):
        return None
    try:
        with open(_meta_path(upload_id), "r", encoding="utf-8") as file:
            meta = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or meta.get("upload_id") != upload_id:
        return None
    return meta


def _store_meta(meta: dict) -> None:
    directory = os.path.join(upload_root(), str(meta["upload_id"]))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, _META_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(meta, file, ensure_ascii=False)
    os.replace(tmp, path)


def remove_upload(upload_id: str) -> None:
    shutil.rmtree(os.path.join(upload_root(), upload_id), ignore_errors=True)


def sweep_expired_uploads() -> int:
    """Delete upload directories (chunks and metadata) older than the cleanup age."""

    root = upload_root()
    try:
        entries = os.listdir(root)
    except OSError:
        return 0
    deadline = time.time() - cleanup_seconds()
    removed = 0
    for name in entries:
        if "/" in name or "\\" in name or name in (".", ".."):
            continue
        directory = os.path.join(root, name)
        marker = os.path.join(directory, _META_NAME)
        try:
            age_marker = os.path.getmtime(marker)
        except OSError:
            age_marker = None
        if age_marker is None:
            try:
                age_marker = os.path.getmtime(directory)
            except OSError:
                continue
        if age_marker > deadline:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        removed += 1
    return removed


def _parse_metadata(raw: str | None) -> tuple[str, str] | None:
    """Decode tus Upload-Metadata ("key b64,key b64") into (filename, media_type)."""

    if not raw:
        return None
    pairs: dict[str, str] = {}
    for pair in raw.split(","):
        parts = pair.strip().split(" ", 1)
        if len(parts) != 2:
            continue
        try:
            pairs[parts[0]] = base64.b64decode(parts[1], validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return None
    filename = pairs.get("filename")
    media_type = pairs.get("filetype")
    if not filename or not media_type:
        return None
    filename = unquote(filename).strip()
    filename = "".join(ch for ch in filename if ch >= " " and ch != "\x7f")[:512]
    if not filename or len(filename) > 512:
        return None
    return filename, media_type.strip().lower()


async def tus_creation(request: Request, lane: TusLane) -> Response:
    """tus creation (POST) and capability discovery (OPTIONS)."""

    if request.method == "OPTIONS":
        return Response(status_code=204, headers=tus_headers({
            "Tus-Version": TUS_VERSION,
            "Tus-Max-Size": str(lane.max_upload_bytes()),
            "Tus-Extension": "creation",
            "X-Padiem-Tus-Chunk-Max": str(chunk_max_bytes()),
        }))

    scope, failure = await lane.identity(request)
    if failure is not None:
        return failure

    # Opportunistic cleanup keeps the data directory bounded without a new timer.
    sweep_expired_uploads()

    length_raw = (request.headers.get("upload-length") or "").strip()
    if not length_raw or not length_raw.isdecimal():
        return error(400, "invalid_upload", "업로드 크기가 올바르지 않습니다.")
    length = int(length_raw)
    limit = lane.max_upload_bytes()
    if length < 1 or length > limit:
        return error(
            413, "upload_too_large",
            f"파일이 너무 커요 — 최대 {human_bytes(limit)}까지 올릴 수 있어요.",
        )
    parsed = _parse_metadata(request.headers.get("upload-metadata"))
    if parsed is None:
        return error(422, "invalid_document", "파일 이름·종류를 확인하지 못했어요. 다시 시도해 주세요.")
    filename, media_type = parsed
    if not lane.accepts(media_type):
        return error(422, "invalid_document", lane.invalid_type_message)

    upload_id = secrets.token_urlsafe(24)
    meta = {
        "upload_id": upload_id,
        "lane": lane.name,
        "scope": dict(scope),
        "filename": filename,
        "media_type": media_type,
        "length_bytes": length,
        "offset_bytes": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "completed": None,
    }
    _store_meta(meta)
    directory = os.path.join(upload_root(), upload_id)
    os.makedirs(directory, exist_ok=True)
    open(os.path.join(directory, _DATA_NAME), "wb").close()
    return JSONResponse(
        {
            "upload_id": upload_id,
            "offset_bytes": 0,
            "length_bytes": length,
            "chunk_max_bytes": chunk_max_bytes(),
            "max_upload_bytes": limit,
            "lane": lane.name,
        },
        status_code=201,
        headers=tus_headers({"Location": lane.location(request, meta)}),
    )


def _owns(meta: dict, scope: Mapping[str, Any]) -> bool:
    stored = meta.get("scope")
    return isinstance(stored, dict) and dict(stored) == dict(scope)


def _unavailable(lane: TusLane) -> dict:
    return {
        "status": lane.unavailable_status,
        "body": {"error": {"code": lane.unavailable_code, "message": lane.unavailable_message}},
    }


async def tus_resource(request: Request, lane: TusLane) -> Response:
    """tus status (HEAD), append (PATCH) and one-time result pickup (GET)."""

    scope, failure = await lane.identity(request)
    if failure is not None:
        return failure
    upload_id = str(request.path_params.get("upload_id") or "")
    meta = _load_meta(upload_id)
    # A foreign upload and a missing one answer identically (404).
    if meta is None or meta.get("lane") != lane.name or not _owns(meta, scope):
        return error(404, "upload_not_found", lane.not_found_message)

    length = int(meta["length_bytes"])
    offset = int(meta["offset_bytes"])
    completed = meta.get("completed")

    if request.method == "HEAD":
        headers = tus_headers({
            "Upload-Offset": str(offset),
            "Upload-Length": str(length),
        })
        if completed is not None:
            headers["X-Padiem-Upload-Complete"] = "1"
        return Response(status_code=200, headers=headers)

    if request.method == "GET":
        if completed is None:
            return JSONResponse(
                {"upload_id": upload_id, "offset_bytes": offset,
                 "length_bytes": length, "completed": False},
                headers=tus_headers(),
            )
        remove_upload(upload_id)
        return JSONResponse(
            completed.get("body") or {"error": {"code": "upload_failed",
                                                "message": "업로드를 마치지 못했어요."}},
            status_code=int(completed.get("status", 503)), headers=tus_headers(),
        )

    # PATCH
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != TUS_CONTENT_TYPE:
        return error(415, "invalid_upload", "지원하지 않는 업로드 형식입니다.")
    if completed is not None:
        return error(409, "upload_completed", "이미 끝난 업로드입니다.")
    offset_raw = (request.headers.get("upload-offset") or "").strip()
    if not offset_raw or not offset_raw.isdecimal() or int(offset_raw) != offset:
        return error(409, "offset_mismatch", "업로드 위치가 맞지 않습니다. 새로고침 후 다시 시도해 주세요.")

    allowed = min(chunk_max_bytes(), length - offset)
    if allowed <= 0:
        return error(409, "offset_mismatch", "업로드 위치가 맞지 않습니다. 새로고침 후 다시 시도해 주세요.")
    data_path = os.path.join(upload_root(), upload_id, _DATA_NAME)
    try:
        # Receive into the same bounded spool the direct routes use, so an
        # oversized PATCH never appends a single byte before it is refused.
        async with open_bounded_spooled_request(request, max_bytes=allowed) as spool:
            written = 0
            with open(data_path, "r+b") as data:
                data.seek(offset)
                while True:
                    block = spool.read(1024 * 1024)
                    if not block:
                        break
                    data.write(block)
                    written += len(block)
    except RequestBodyTooLarge:
        return error(
            413, "chunk_too_large",
            f"조각이 너무 커요 — 한 번에 최대 {human_bytes(chunk_max_bytes())}까지 보낼 수 있어요.",
        )
    except OSError:
        return error(lane.unavailable_status, lane.unavailable_code, lane.unavailable_message)

    offset += written
    meta["offset_bytes"] = offset
    meta["updated_at"] = time.time()
    if offset >= length:
        try:
            meta["completed"] = await lane.finalize(request, data_path, meta)
        except Exception:
            meta["completed"] = _unavailable(lane)
    _store_meta(meta)
    return Response(status_code=204, headers=tus_headers({"Upload-Offset": str(offset)}))


__all__ = [
    "DEFAULT_CHUNK_MAX_BYTES",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "TUS_CONTENT_TYPE",
    "TUS_VERSION",
    "TusLane",
    "chunk_max_bytes",
    "cleanup_seconds",
    "error",
    "human_bytes",
    "max_upload_bytes",
    "remove_upload",
    "sweep_expired_uploads",
    "tus_creation",
    "tus_headers",
    "tus_resource",
    "upload_root",
]
