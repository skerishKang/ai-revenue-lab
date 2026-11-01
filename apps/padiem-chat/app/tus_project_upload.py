"""tus 1.0.0 core for resumable project-file uploads (대표 결정: 상한 1GB 통일).

Implements the three core protocol verbs on top of the existing authenticated
project-file flow — creation (POST, Upload-Length), append (PATCH,
Upload-Offset), status (HEAD) — plus a one-time result pickup (GET). The
protocol is implemented here directly: the server side takes no new third-party
dependency. The browser side uses the vendored MIT tus-js-client
(``static/tus-js-client-4.3.1.min.js``, license file next to it and an entry in
``static/third-party-licenses.html``).

Design decisions pinned by ops lessons and the design doc
(docs/research/LARGE_UPLOAD_1GB_DESIGN_20261101.md, A안):

- Chunks stay under the Cloudflare free-plan request-body limit: the per-PATCH
  ceiling defaults to 90 MiB and is configurable (PADIEM_TUS_CHUNK_MAX_BYTES).
- The total upload ceiling defaults to the project binary row bound
  (MAX_BINARY_DOCUMENT_BYTES, 1 GiB) and is configurable
  (PADIEM_TUS_MAX_UPLOAD_BYTES); the browser reads the same values from this
  endpoint's responses instead of keeping its own constant.
- Temporary chunk files live in the systemd-writable data path only
  (11-01 운영 교훈 8-1): PADIEM_TUS_UPLOAD_DIR, or under
  PADIEM_CHAT_LOCAL_DATA_DIR when set, or the private temp dir. Never on /mnt/d.
- Upload IDs are unguessable (secrets.token_urlsafe) and every request is
  re-checked against the signed-in owner and the URL's project, so another
  user's upload URL behaves exactly like a missing one (404).
- Incomplete uploads are swept after PADIEM_TUS_CLEANUP_SECONDS (default 24h);
  the sweep runs opportunistically on every creation and is exposed for the
  cron timer.
- Completion hands off to the unchanged project-file save flow
  (project_file_routes.save_binary_project_file): same parsing authority, same
  doc_kind rules, same original-bytes object storage. The client picks the
  stored result up with GET (201 file / 4xx error) after the final PATCH.
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
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_ai_core.document_normalization import DocumentNormalizationError

from .bounded_request_body import RequestBodyTooLarge, open_bounded_spooled_request
from .documents import DocumentValidationError
from .project_files import BINARY_PROJECT_FILE_MEDIA, ProjectFileLimitError
from .project_file_routes import (
    OriginalStorageUnavailable,
    _identity,
    save_binary_project_file,
)

TUS_VERSION = "1.0.0"
TUS_CONTENT_TYPE = "application/offset+octet-stream"
_META_NAME = "upload.json"
_DATA_NAME = "data.bin"

DEFAULT_CHUNK_MAX_BYTES = 90 * 1024 * 1024


def _int_setting(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw or not raw.isdecimal():
        return default
    return int(raw)


def chunk_max_bytes() -> int:
    return _int_setting("PADIEM_TUS_CHUNK_MAX_BYTES", DEFAULT_CHUNK_MAX_BYTES)


def max_upload_bytes() -> int:
    return _int_setting("PADIEM_TUS_MAX_UPLOAD_BYTES", 1073741824)


def cleanup_seconds() -> int:
    return _int_setting("PADIEM_TUS_CLEANUP_SECONDS", 86400)


def _upload_root() -> str:
    configured = (os.environ.get("PADIEM_TUS_UPLOAD_DIR") or "").strip()
    if configured:
        return configured
    data_dir = (os.environ.get("PADIEM_CHAT_LOCAL_DATA_DIR") or "").strip()
    if data_dir:
        return os.path.join(data_dir, "tus-uploads")
    # The service runs with PrivateTmp, so the system temp dir is a writable
    # per-service path even under ProtectSystem=strict (11-01 lesson 8-1).
    return os.path.join(tempfile.gettempdir(), "padiem-tus-uploads")


def _human_bytes(total: int) -> str:
    value = float(total)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit in ("B", "KB", "MB") else f"{value:.1f}GB"
        value /= 1024
    return f"{total}B"


def _tus_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Tus-Resumable": TUS_VERSION,
        "Cache-Control": "no-store",
    }
    if extra:
        headers.update(extra)
    return headers


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=_tus_headers(headers))


def _meta_path(upload_id: str) -> str:
    return os.path.join(_upload_root(), upload_id, _META_NAME)


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
    directory = os.path.join(_upload_root(), str(meta["upload_id"]))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, _META_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(meta, file, ensure_ascii=False)
    os.replace(tmp, path)


def _remove_upload(upload_id: str) -> None:
    shutil.rmtree(os.path.join(_upload_root(), upload_id), ignore_errors=True)


def sweep_expired_uploads() -> int:
    """Delete upload directories (chunks and metadata) older than the cleanup age."""

    root = _upload_root()
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


async def project_file_tus_collection(request: Request):
    """tus creation (POST) and capability discovery (OPTIONS)."""

    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers=_tus_headers({
                "Tus-Version": TUS_VERSION,
                "Tus-Max-Size": str(max_upload_bytes()),
                "Tus-Extension": "creation",
                "X-Padiem-Tus-Chunk-Max": str(chunk_max_bytes()),
            }),
        )

    uid, pid, error = await _identity(request)
    if error is not None:
        return error

    # Opportunistic cleanup keeps the data directory bounded without a new timer.
    sweep_expired_uploads()

    length_raw = (request.headers.get("upload-length") or "").strip()
    if not length_raw or not length_raw.isdecimal():
        return _error(400, "invalid_upload", "업로드 크기가 올바르지 않습니다.")
    length = int(length_raw)
    limit = max_upload_bytes()
    if length < 1 or length > limit:
        return _error(
            413, "upload_too_large",
            f"파일이 너무 커요 — 최대 {_human_bytes(limit)}까지 올릴 수 있어요.",
        )
    parsed = _parse_metadata(request.headers.get("upload-metadata"))
    if parsed is None:
        return _error(422, "invalid_document", "파일 이름·종류를 확인하지 못했어요. 다시 시도해 주세요.")
    filename, media_type = parsed
    if media_type not in BINARY_PROJECT_FILE_MEDIA:
        return _error(422, "invalid_document", "이 형식은 프로젝트 파일로 올릴 수 없습니다.")

    upload_id = secrets.token_urlsafe(24)
    meta = {
        "upload_id": upload_id,
        "user_id": uid,
        "project_id": pid,
        "filename": filename,
        "media_type": media_type,
        "length_bytes": length,
        "offset_bytes": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "completed": None,
    }
    _store_meta(meta)
    open(os.path.join(_upload_root(), upload_id, _DATA_NAME), "wb").close()
    location = f"/api/projects/{pid}/files/tus/{upload_id}"
    return JSONResponse(
        {
            "upload_id": upload_id,
            "offset_bytes": 0,
            "length_bytes": length,
            "chunk_max_bytes": chunk_max_bytes(),
            "max_upload_bytes": limit,
        },
        status_code=201,
        headers=_tus_headers({"Location": location}),
    )


def _owns(meta: dict, uid: str, pid: str) -> bool:
    return meta.get("user_id") == uid and meta.get("project_id") == pid


def _unavailable_result() -> dict:
    return {
        "status": 503,
        "body": {"error": {"code": "project_files_unavailable", "message": "프로젝트 파일을 현재 사용할 수 없습니다."}},
    }


def _validation_failure(exc: Exception, media_type: str) -> dict:
    # The direct route's exact 422 mapping, so both entry points answer alike.
    if media_type == "application/hwp+zip":
        from .binary_documents import guidance_for_reason_code
        message = guidance_for_reason_code(getattr(exc, "code", ""), media_type)
        message = message or "HWPX 파일을 읽지 못했습니다. 파일을 확인해 주세요."
    else:
        message = str(exc)
    return {"status": 422, "body": {"error": {"code": "invalid_document", "message": message}}}


async def _finalize(request: Request, meta: dict) -> dict:
    """Run the unchanged project-file save flow over the completed chunk file."""

    data_path = os.path.join(_upload_root(), str(meta["upload_id"]), _DATA_NAME)
    media_type = str(meta["media_type"])
    try:
        with open(data_path, "rb") as data:
            try:
                created = await save_binary_project_file(
                    request,
                    uid=str(meta["user_id"]), pid=str(meta["project_id"]),
                    name=str(meta["filename"]), media_type=media_type,
                    data=data,
                )
            except RequestBodyTooLarge:
                return {"status": 413, "body": {"error": {"code": "invalid_document", "message": "파일이 너무 커요."}}}
            except (ValueError, DocumentNormalizationError, DocumentValidationError, ProjectFileLimitError) as exc:
                return _validation_failure(exc, media_type)
            except OriginalStorageUnavailable:
                return _unavailable_result()
            except Exception:
                return _unavailable_result()
        return {"status": 201, "body": {"file": created.public_dict()}}
    except OSError:
        return _unavailable_result()


async def project_file_tus_item(request: Request):
    """tus status (HEAD), append (PATCH) and one-time result pickup (GET)."""

    uid, pid, error = await _identity(request)
    if error is not None:
        return error
    upload_id = str(request.path_params.get("upload_id") or "")
    meta = _load_meta(upload_id)
    if meta is None or not _owns(meta, uid, pid):
        return _error(404, "project_file_not_found", "프로젝트 파일을 찾을 수 없습니다.")

    length = int(meta["length_bytes"])
    offset = int(meta["offset_bytes"])
    completed = meta.get("completed")

    if request.method == "HEAD":
        headers = _tus_headers({
            "Upload-Offset": str(offset),
            "Upload-Length": str(length),
        })
        if completed is not None:
            headers["X-Padiem-Upload-Complete"] = "1"
        return Response(status_code=200, headers=headers)

    if request.method == "GET":
        if completed is None:
            return JSONResponse(
                {"upload_id": upload_id, "offset_bytes": offset, "length_bytes": length, "completed": False},
                headers=_tus_headers(),
            )
        _remove_upload(upload_id)
        return JSONResponse(completed.get("body") or {"error": {"code": "upload_failed", "message": "업로드를 마치지 못했어요."}}, status_code=int(completed.get("status", 503)), headers=_tus_headers())

    # PATCH
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != TUS_CONTENT_TYPE:
        return _error(415, "invalid_upload", "지원하지 않는 업로드 형식입니다.")
    if completed is not None:
        return _error(409, "upload_completed", "이미 끝난 업로드입니다.")
    offset_raw = (request.headers.get("upload-offset") or "").strip()
    if not offset_raw or not offset_raw.isdecimal() or int(offset_raw) != offset:
        return _error(409, "offset_mismatch", "업로드 위치가 맞지 않습니다. 새로고침 후 다시 시도해 주세요.")

    allowed = min(chunk_max_bytes(), length - offset)
    if allowed <= 0:
        return _error(409, "offset_mismatch", "업로드 위치가 맞지 않습니다. 새로고침 후 다시 시도해 주세요.")
    data_path = os.path.join(_upload_root(), upload_id, _DATA_NAME)
    try:
        # Receive into the same bounded spool the direct route uses, so an
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
        return _error(
            413, "chunk_too_large",
            f"조각이 너무 커요 — 한 번에 최대 {_human_bytes(chunk_max_bytes())}까지 보낼 수 있어요.",
        )
    except OSError:
        return _error(503, "project_files_unavailable", "프로젝트 파일을 현재 사용할 수 없습니다.")

    offset += written
    meta["offset_bytes"] = offset
    meta["updated_at"] = time.time()
    if offset >= length:
        meta["completed"] = await _finalize(request, meta)
    _store_meta(meta)
    return Response(status_code=204, headers=_tus_headers({"Upload-Offset": str(offset)}))
