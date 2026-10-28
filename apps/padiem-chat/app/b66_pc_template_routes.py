"""#5895 — the B66 quote screen's "my PC Excel form" lane, Chat half.

The owner picks a quotation workbook from their own PC. Its cells are read and filled
in the COM2 file lane, where openpyxl lives: this Worker never imports a workbook
parser, because the cold-init regression on 2026-10-28 came from exactly that kind of
extra import weight (#6034). What Chat does here is exchange identities:

* the PC's own fetched bytes are handed to the lane under this owner's upload ticket;
* the lane answers the form's structure (cells, merges, formulas);
* a helper model is shown that structure and the owner's request and answers which
  cell receives which value — the mapping is the model's decision, not a label rule,
  because every customer's form lays its labels out differently;
* the lane fills a *copy* and answers a new file id.

Saving is the shared `/api/pc/save` with that lane id: the filled workbook goes to the
PC as a new file next to the form, the original is never overwritten, and the write
still takes the backup #5573 makes first. The prompt in this module is the only thing
that knows both sides, and it carries no customer identifiers beyond what the owner
already typed into the quote screen.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .pc_file_exchange_routes import (
    DISPATCH_ID,
    _dispatch_row,
    _stored_output,
)

PC_QUOTE_FILL_PATH = "/api/b66/pc-quote/fill"
_MAX_REQUEST_CHARS = 4000
_NAME_SAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_ADDRESS = re.compile(r"[A-Z]{1,3}[1-9][0-9]{0,6}")

_MAPPING_SYSTEM = (
    "당신은 엑셀 견적서 양식을 채우는 도우미입니다. "
    "아래에 사용자의 견적서 양식 구조(비어 있지 않은 셀 주소와 표시 값, 병합 셀, 수식)와 "
    "사용자의 요청이 주어집니다. 요청의 값이 들어갈 셀을 정하세요.\n"
    "- 값은 라벨 바로 옆이나 아래의 빈 셀에 넣습니다. 라벨 글자와 수식 셀은 절대 덮지 않습니다.\n"
    "- 품목 행이 모자라면 extend에 {\"sheet\": 시트, \"template_row\": 마지막 품목 행 번호, "
    "\"at_row\": 새 행이 시작할 번호, \"count\": 늘릴 행 수}를 적습니다.\n"
    "- 합계 등 기존 수식은 그대로 둡니다.\n"
    "- 응답은 설명 없이 JSON 하나만: "
    "{\"client\": \"거래처 이름\", \"mapping\": {\"시트\": {\"셀주소\": 값}}, \"extend\": [...]}\n"
    "- 숫자는 숫자로, 날짜는 YYYY-MM-DD 문자열로 적습니다."
)


_NO_STORE = {"Cache-Control": "no-store, max-age=0"}


def _error(status: int, code: str) -> JSONResponse:
    """The same refusal shape the PC routes answer with; nothing else is echoed."""

    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status,
                        headers=_NO_STORE)


def _cli(request: Request) -> Any:
    return getattr(request.app.state, "file_lane_client", None)


def _owner(request: Request) -> str | JSONResponse:
    if not auth_ready(request):
        return _error(401, "canonical_session_required")
    uid = current_user_id(request)
    return uid if isinstance(uid, str) and uid else _error(401, "canonical_session_required")


def _lane_headers(client: Any, uid: str, *, upload: int | None = None) -> dict[str, str]:
    headers, _expires = (client.upload_ticket(uid, upload) if upload is not None
                         else client.read_ticket(uid))
    return headers


async def _lane_upload(client: Any, uid: str, name: str, data: bytes) -> str | None:
    try:
        headers = _lane_headers(client, uid, upload=len(data))
        async with httpx.AsyncClient(
            transport=getattr(client, "_transport", None), timeout=None,
            follow_redirects=False, trust_env=False,
        ) as http:
            response = await http.post(
                client.origin + "/files", params={"filename": name},
                headers=headers, content=data,
            )
            if response.status_code != 201:
                return None
            body = response.json()
    except Exception:
        return None
    file_id = body.get("file_id") if isinstance(body, dict) else None
    return file_id if isinstance(file_id, str) and file_id.startswith("file_") else None


async def _lane_json(
    client: Any, uid: str, *, method: str, path: str, payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        headers = _lane_headers(client, uid)
        async with httpx.AsyncClient(
            transport=getattr(client, "_transport", None), timeout=None,
            follow_redirects=False, trust_env=False,
        ) as http:
            response = await http.request(
                method, client.origin + path, headers=headers, json=payload,
            )
            if response.status_code not in (200, 201):
                return None
            body = response.json()
    except Exception:
        return None
    return body if isinstance(body, dict) and body.get("ok") is True else None


def _model_mapping(answer: Any) -> dict[str, Any] | None:
    """The mapping the helper model answered, or None when it is not the asked shape."""

    if not isinstance(answer, str):
        return None
    text = answer.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    mapping = value.get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        return None
    for sheet, cells in mapping.items():
        if not isinstance(sheet, str) or not isinstance(cells, dict):
            return None
        for address in cells:
            if not isinstance(address, str) or _ADDRESS.fullmatch(address) is None:
                return None
    extend = value.get("extend")
    if extend is not None and not isinstance(extend, list):
        return None
    client_name = value.get("client")
    return {
        "client": client_name.strip() if isinstance(client_name, str) else "",
        "mapping": mapping,
        "extend": extend or [],
    }


def _filled_name(client_name: str, day: str) -> str:
    safe = _NAME_SAFE.sub(" ", client_name).strip() or "거래처"
    return "견적서_" + safe + "_" + day + ".xlsx"


async def pc_quote_fill(request: Request) -> JSONResponse:
    """One picked PC workbook, answered as a filled copy held by the file lane."""

    # Imported here, not at module load: the mesh lane's module must stay out of the
    # Worker's cold init (#6034), and this route is the only thing that needs it.
    from .oracle_mesh_read_return_routes import _read_body, _response, _text_value

    body = await _read_body(
        request, frozenset({"file_id", "request"}), optional=frozenset({"today"}),
    )
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    uid = _owner(request)
    if isinstance(uid, JSONResponse):
        return uid
    file_id = body.get("file_id")
    if not isinstance(file_id, str) or DISPATCH_ID.fullmatch(file_id) is None:
        return _error(404, "pc_dispatch_not_found")
    asked = _text_value(body.get("request"), limit=_MAX_REQUEST_CHARS)
    if asked is None or not asked.strip():
        return _error(422, "quote_request_required")
    day = body.get("today")
    if not isinstance(day, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is None:
        from datetime import datetime, timezone

        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    client = _cli(request)
    if client is None or getattr(client, "ready", False) is not True:
        return _error(503, "file_lane_unavailable")
    dispatch = await _dispatch_row(request, uid, file_id)
    if isinstance(dispatch, JSONResponse):
        return dispatch
    if dispatch.get("state") != "done":
        return _error(409, "oracle_mesh_result_not_ready")
    data, refusal = await _stored_output(request, uid, dispatch)
    if refusal is not None:
        return refusal
    template_name = str(dispatch.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1] or "견적서 양식.xlsx"
    if not template_name.lower().endswith(".xlsx"):
        return _error(422, "pc_quote_template_format")

    lane_id = await _lane_upload(client, uid, template_name, data)
    if lane_id is None:
        return _error(502, "file_lane_unavailable")
    structure = await _lane_json(client, uid, method="GET", path="/files/" + lane_id + "/structure")
    if structure is None:
        return _error(502, "file_lane_unavailable")

    interpreter = getattr(request.app.state, "b66_quote_interpreter", None)
    completer = getattr(getattr(interpreter, "_client", None), "complete", None)
    if not callable(completer):
        return _error(503, "quote_runtime_unavailable")
    try:
        result = await completer(
            [{"role": "user", "content": asked.strip()}],
            additional_system_context=_MAPPING_SYSTEM + "\n\n양식 구조:\n"
            + json.dumps(structure, ensure_ascii=False)[:_MAX_REQUEST_CHARS * 8],
            attachments=(),
        )
    except Exception:
        return _error(502, "quote_template_mapping_failed")
    answer = result.get("answer") if isinstance(result, dict) else None
    decided = _model_mapping(answer)
    if decided is None:
        return _error(502, "quote_template_mapping_failed")

    name = _filled_name(decided["client"], day)
    filled = await _lane_json(
        client, uid, method="POST", path="/files/" + lane_id + "/fill",
        payload={"mapping": decided["mapping"], "extend": decided["extend"], "filename": name},
    )
    if filled is None:
        return _error(502, "quote_template_fill_failed")
    return _response({
        "ok": True,
        "filled_file_id": filled.get("file_id"),
        "filled_name": filled.get("name") or name,
        "template_name": template_name,
        "client": decided["client"],
        "mapping": decided["mapping"],
        "extend": decided["extend"],
    })
