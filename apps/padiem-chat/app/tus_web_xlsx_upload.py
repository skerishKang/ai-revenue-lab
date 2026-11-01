"""Web XLSX lane over the shared tus core (#6579 → 1GB step 2, item 1).

The Owner's ceiling for a web Office XLSX is already 1 GiB
(``workspace_storage.MAX_WEB_XLSX_BYTES``); what actually capped uploads at
~100 MB was the Cloudflare free-plan request-body limit on the way in. This lane
removes that cap by reusing the shared tus core: the browser sends <=90 MiB
chunks, and the completed file is handed to the unchanged web-XLSX save flow
(``put_web_xlsx``) — same OOXML validation, same 081 selection rows, same
retention.

Only what is genuinely this lane's own lives here:

* the owner scope is ``(user_id, workspace_id)``, resolved through the existing
  web-source authority (signed-in user + their memory workspace + a bound
  workspace document store);
* the accepted type is the workbook media type;
* the ceiling is the existing web-XLSX constant, not a new number;
* the Location points at this lane's address under the existing web-source path.

A completed upload is never readable as bytes from this lane: the one-time GET
answers with the created document projection, which is the same shape
``POST /api/claw/office/web-sources`` already returns.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from .auth_routes import auth_ready, current_user_id
from .claw_memory_routes import _resolve_memory_workspace
from .tus_core import TusLane, error, tus_creation, tus_resource
from .workspace_storage import MAX_WEB_XLSX_BYTES, XLSX_MEDIA_TYPE

LANE_NAME = "web_xlsx"
WEB_XLSX_TUS_COLLECTION_PATH = "/api/claw/office/web-sources/tus"
WEB_XLSX_TUS_ITEM_PATH = "/api/claw/office/web-sources/tus/{upload_id}"
CONTRACT_VERSION = "claw-web-xlsx-source.v1"
NOT_FOUND_MESSAGE = "업로드를 찾을 수 없습니다."


def web_xlsx_lane() -> TusLane:
    return TusLane(
        name=LANE_NAME,
        identity=_web_xlsx_identity,
        finalize=_finalize_web_xlsx,
        accepts=lambda media_type: media_type == XLSX_MEDIA_TYPE,
        location=_location,
        max_upload_bytes=lambda: MAX_WEB_XLSX_BYTES,
        invalid_type_message="엑셀(.xlsx) 파일만 올릴 수 있습니다.",
        not_found_message=NOT_FOUND_MESSAGE,
        unavailable_code="web_xlsx_save_unavailable",
        unavailable_message="엑셀 파일을 현재 저장할 수 없습니다.",
    )


async def _web_xlsx_identity(request: Request):
    """The web-source authority, unchanged: session → workspace → store."""
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return None, error(401, "unauthorized", "로그인이 필요합니다.")
    workspace = await _resolve_memory_workspace(request, owner)
    if not workspace:
        return None, error(503, "workspace_authority_unavailable",
                           "작업 공간을 확인할 수 없습니다.")
    if getattr(request.app.state, "workspace_document_store", None) is None:
        return None, error(503, "web_xlsx_store_unavailable",
                           "엑셀 파일을 현재 저장할 수 없습니다.")
    return {"user_id": owner, "workspace_id": workspace}, None


def _location(request: Request, meta: dict) -> str:
    return f"/api/claw/office/web-sources/tus/{meta['upload_id']}"


async def _finalize_web_xlsx(request: Request, data_path: str, meta: dict) -> dict:
    """Hand the completed upload to the unchanged web-XLSX save flow.

    ``put_web_xlsx`` owns validation (OOXML archive, workbook members) and the
    081 selection store, exactly as the inline route does — so a tus upload and
    an inline upload cannot end up in different states. The bytes are read whole
    because that is the existing store's contract; the ceiling that read obeys
    is the same ``MAX_WEB_XLSX_BYTES`` the inline route already enforces.
    """
    store = getattr(request.app.state, "workspace_document_store", None)
    if store is None:
        return _unavailable()
    scope = meta["scope"]
    try:
        with open(data_path, "rb") as data:
            body = data.read()
    except OSError:
        return _unavailable()
    try:
        file = await store.put_web_xlsx(
            tenant_id=scope["workspace_id"], owner_id=scope["user_id"],
            workspace_id=scope["workspace_id"],
            filename=str(meta["filename"]), body=body,
        )
    except ValueError:
        return {"status": 422, "body": {"ok": False,
                                        "error": {"code": "invalid_web_xlsx_file"}}}
    except Exception:
        return _unavailable()
    return {
        "status": 201,
        "body": {
            "ok": True, "contract_version": CONTRACT_VERSION,
            "file": file, "source": "browser_upload",
            "processing_started": False, "p01_approved": False,
            "drive_uploaded": False,
        },
    }


def _unavailable() -> dict:
    return {"status": 503, "body": {"ok": False,
                                    "error": {"code": "web_xlsx_save_unavailable"}}}


async def web_xlsx_tus_collection(request: Request) -> Response:
    """tus creation (POST) and capability discovery (OPTIONS)."""
    return await tus_creation(request, web_xlsx_lane())


async def web_xlsx_tus_item(request: Request) -> Response:
    """tus status (HEAD), append (PATCH) and one-time result pickup (GET)."""
    return await tus_resource(request, web_xlsx_lane())


__all__ = [
    "LANE_NAME",
    "WEB_XLSX_TUS_COLLECTION_PATH",
    "WEB_XLSX_TUS_ITEM_PATH",
    "web_xlsx_lane",
    "web_xlsx_tus_collection",
    "web_xlsx_tus_item",
]
