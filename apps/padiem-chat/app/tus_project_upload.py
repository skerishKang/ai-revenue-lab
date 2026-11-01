"""Project-file lane over the shared tus core (#6579 → 1GB step 2).

The tus protocol itself lives in ``app/tus_core.py`` so the web XLSX and Chat
attachment lanes reuse it instead of copying it. This module supplies only what
is genuinely the project lane's own:

* the owner scope is ``(user_id, project_id)``, read through the unchanged
  project-file identity check (signed-in owner, project the owner really has);
* the accepted media types are the project binary set
  (``BINARY_PROJECT_FILE_MEDIA``);
* the Location points at this lane's existing address shape;
* completion hands off to the unchanged project-file save flow
  (``save_binary_project_file``): same parsing authority, same doc_kind rules,
  same original-bytes object storage.

The route handlers keep their existing names, paths and answers, so nothing that
already depended on the #6579 surface changes.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from padiem_ai_core.document_normalization import DocumentNormalizationError

from .bounded_request_body import RequestBodyTooLarge
from .documents import DocumentValidationError
from .project_files import BINARY_PROJECT_FILE_MEDIA, ProjectFileLimitError
from .project_file_routes import (
    OriginalStorageUnavailable,
    _identity,
    save_binary_project_file,
)
from .tus_core import (
    DEFAULT_CHUNK_MAX_BYTES,
    TUS_VERSION,
    TusLane,
    chunk_max_bytes,
    cleanup_seconds,
    max_upload_bytes,
    sweep_expired_uploads,
    tus_creation,
    tus_resource,
)

LANE_NAME = "project_file"
NOT_FOUND_MESSAGE = "프로젝트 파일을 찾을 수 없습니다."


def _unavailable_result() -> dict:
    return {
        "status": 503,
        "body": {"error": {"code": "project_files_unavailable",
                           "message": "프로젝트 파일을 현재 사용할 수 없습니다."}},
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


async def _project_identity(request: Request):
    uid, pid, failure = await _identity(request)
    if failure is not None:
        return None, failure
    return {"user_id": uid, "project_id": pid}, None


async def _finalize(request: Request, data_path: str, meta: dict) -> dict:
    """Run the unchanged project-file save flow over the completed chunk file."""

    media_type = str(meta["media_type"])
    try:
        with open(data_path, "rb") as data:
            try:
                created = await save_binary_project_file(
                    request,
                    uid=str(meta["scope"]["user_id"]),
                    pid=str(meta["scope"]["project_id"]),
                    name=str(meta["filename"]), media_type=media_type,
                    data=data,
                )
            except RequestBodyTooLarge:
                return {"status": 413, "body": {"error": {
                    "code": "invalid_document", "message": "파일이 너무 커요."}}}
            except (ValueError, DocumentNormalizationError, DocumentValidationError,
                    ProjectFileLimitError) as exc:
                return _validation_failure(exc, media_type)
            except OriginalStorageUnavailable:
                return _unavailable_result()
            except Exception:
                return _unavailable_result()
        return {"status": 201, "body": {"file": created.public_dict()}}
    except OSError:
        return _unavailable_result()


def _location(request: Request, meta: dict) -> str:
    return f"/api/projects/{meta['scope']['project_id']}/files/tus/{meta['upload_id']}"


def project_lane() -> TusLane:
    return TusLane(
        name=LANE_NAME,
        identity=_project_identity,
        finalize=_finalize,
        accepts=lambda media_type: media_type in BINARY_PROJECT_FILE_MEDIA,
        location=_location,
        max_upload_bytes=max_upload_bytes,
        invalid_type_message="이 형식은 프로젝트 파일로 올릴 수 없습니다.",
        not_found_message=NOT_FOUND_MESSAGE,
        unavailable_code="project_files_unavailable",
        unavailable_message="프로젝트 파일을 현재 사용할 수 없습니다.",
    )


async def project_file_tus_collection(request: Request) -> Response:
    """tus creation (POST) and capability discovery (OPTIONS)."""
    return await tus_creation(request, project_lane())


async def project_file_tus_item(request: Request) -> Response:
    """tus status (HEAD), append (PATCH) and one-time result pickup (GET)."""
    return await tus_resource(request, project_lane())


__all__ = [
    "DEFAULT_CHUNK_MAX_BYTES",
    "LANE_NAME",
    "TUS_VERSION",
    "chunk_max_bytes",
    "cleanup_seconds",
    "max_upload_bytes",
    "project_file_tus_collection",
    "project_file_tus_item",
    "project_lane",
    "sweep_expired_uploads",
]
