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
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .b66_saved_quote_skill_store import (
    SKILL_KIND_PC_FORM,
    SavedQuoteSkillStoreError,
    build_pc_form_artifact,
    validate_row_id,
)
from .claw_memory_routes import _resolve_memory_workspace
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


def _confirmed_value_mapping(answer: Any, confirmed: dict, structure: dict) -> dict | None:
    """Apply values by confirmed roles only; ignore any model-supplied cell addresses."""
    if not isinstance(answer, str):
        return None
    try:
        start, end = answer.find("{"), answer.rfind("}")
        result = json.loads(answer[start:end + 1]) if start >= 0 and end > start else None
    except ValueError:
        return None
    if not isinstance(result, dict) or not isinstance(result.get("values"), dict):
        return None
    values = result["values"]
    if set(values) - set(confirmed):
        return None
    formulas = {(sheet.get("name"), cell.get("cell")) for sheet in structure.get("sheets", [])
                for cell in sheet.get("cells", []) if cell.get("formula")}
    occupied = {(sheet.get("name"), cell.get("cell")) for sheet in structure.get("sheets", [])
                for cell in sheet.get("cells", []) if str(cell.get("text", "")).strip()}
    mapping = {}
    item_roles = {"item", "quantity", "unit_price", "amount"}
    for role, value in values.items():
        slot = confirmed[role]
        sequence = value if isinstance(value, list) and role in item_roles else [value]
        match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", slot["cell"])
        if not match or not sequence:
            return None
        for offset, entry in enumerate(sequence):
            if isinstance(entry, (dict, list)) or entry is None or isinstance(entry, bool):
                return None
            address = match.group(1) + str(int(match.group(2)) + offset)
            if (slot["sheet"], address) in formulas or (slot["sheet"], address) in occupied:
                return None
            sheet = mapping.setdefault(slot["sheet"], {})
            if address in sheet:
                return None
            sheet[address] = entry
    if not mapping:
        return None
    client = result.get("client", "")
    return {"client": client.strip() if isinstance(client, str) else "",
            "mapping": mapping, "extend": []}


def _filled_name(client_name: str, day: str) -> str:
    safe = _NAME_SAFE.sub(" ", client_name).strip() or "거래처"
    return "견적서_" + safe + "_" + day + ".xlsx"


async def _saved_form(
    request: Request, uid: str, form_id: Any, template_path: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None] | tuple[JSONResponse, None]:
    """The owner's registered form for this exact workbook, or a refusal.

    ``None`` means "no saved form was named": the caller describes the workbook
    on the spot, exactly as before #3180 ③.
    """

    if form_id is None:
        return None, None
    if not isinstance(form_id, str):
        return _error(422, "form_id_invalid"), None
    try:
        clean_id = validate_row_id(form_id)
    except SavedQuoteSkillStoreError:
        return _error(422, "form_id_invalid"), None
    store = getattr(request.app.state, "b66_saved_quote_skill_store", None)
    if not callable(getattr(store, "get_skill", None)):
        return _error(503, "saved_quote_skill_unavailable"), None
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        return _error(503, "workspace_unavailable"), None
    if not isinstance(workspace_id, str) or not workspace_id:
        return _error(503, "workspace_unavailable"), None
    try:
        record = store.get_skill(user_id=uid, workspace_id=workspace_id, saved_skill_id=clean_id)
        if hasattr(record, "__await__"):
            record = await record
    except Exception:
        return _error(503, "saved_quote_skill_unavailable"), None
    if not isinstance(record, dict):
        return _error(404, "form_not_found"), None
    if record.get("skill_kind") != SKILL_KIND_PC_FORM:
        return _error(409, "form_not_a_pc_form"), None
    skill = record.get("skill") if isinstance(record.get("skill"), dict) else {}
    form = skill.get("form")
    if not isinstance(form, dict):
        return _error(409, "form_invalid"), None
    # The saved form is bound to the file it was registered from. Filling some
    # other workbook under that name would put the wrong company's form under a
    # familiar label, so it is refused rather than guessed at.
    if form.get("path") != template_path:
        return _error(409, "form_path_mismatch"), None
    return form, record


async def _remember_item_rows(
    request: Request, uid: str, record: dict[str, Any] | None,
    form: dict[str, Any], extend: list[Any],
) -> None:
    """Store the row-growth pattern this fill needed on the same saved form."""

    if not isinstance(record, dict) or not isinstance(extend, list):
        return
    store = getattr(request.app.state, "b66_saved_quote_skill_store", None)
    if not callable(getattr(store, "put_approved_skill", None)):
        return
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
        if not isinstance(workspace_id, str) or not workspace_id:
            return
        artifact = build_pc_form_artifact(
            skill_id=record.get("skill_id"),
            skill_name=record.get("skill_name"),
            form={**form, "item_rows": extend},
            approved_at="",
        )
        written = store.put_approved_skill(
            user_id=uid, workspace_id=workspace_id, artifact=artifact,
        )
        if hasattr(written, "__await__"):
            await written
    except Exception:
        # The fill already succeeded; a pattern we could not remember must not
        # turn a delivered workbook into an error.
        return


async def pc_quote_fill(request: Request) -> JSONResponse:
    """One picked PC workbook, answered as a filled copy held by the file lane."""

    # Imported here, not at module load: the mesh lane's module must stay out of the
    # Worker's cold init (#6034), and this route is the only thing that needs it.
    from .oracle_mesh_read_return_routes import _read_body, _response, _text_value

    body = await _read_body(
        request, frozenset({"file_id", "request"}),
        optional=frozenset({"today", "form_id"}),
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
    template_path = str(dispatch.get("file_path") or "").replace("\\", "/").strip()
    template_name = template_path.rsplit("/", 1)[-1] or "견적서 양식.xlsx"
    if not template_name.lower().endswith(".xlsx"):
        return _error(422, "pc_quote_template_format")

    # #3180 ③: a saved form already knows its own structure, so the repeat fill
    # reuses it instead of describing the workbook again — and refuses a file
    # that is not the one the owner registered under that form.
    saved_form, saved_record = await _saved_form(request, uid, body.get("form_id"), template_path)
    if isinstance(saved_form, JSONResponse):
        return saved_form

    lane_id = await _lane_upload(client, uid, template_name, data)
    if lane_id is None:
        return _error(502, "file_lane_unavailable")
    if saved_form is None:
        structure = await _lane_json(client, uid, method="GET", path="/files/" + lane_id + "/structure")
        if structure is None:
            return _error(502, "file_lane_unavailable")
    else:
        structure = {"sheets": saved_form["structure"]["sheets"]}

    interpreter = getattr(request.app.state, "b66_quote_interpreter", None)
    completer = getattr(getattr(interpreter, "_client", None), "complete", None)
    if not callable(completer):
        return _error(503, "quote_runtime_unavailable")
    try:
        pattern = ""
        if saved_form is not None and saved_form.get("mapping"):
            pattern += ("\n\n사용자가 확인한 칸 위치(재선택하지 말고 그대로 사용):\n"
                        + json.dumps(saved_form["mapping"], ensure_ascii=False))
        if saved_form is not None and saved_form.get("item_rows"):
            pattern += ("\n\n이 양식에서 지난번 품목 행을 늘린 방식:\n"
                       + json.dumps(saved_form["item_rows"], ensure_ascii=False)[:2000])
        confirmed = saved_form.get("mapping") if saved_form else None
        system = _MAPPING_SYSTEM
        if confirmed:
            system = ("사용자 요청에서 견적 값만 추출하세요. 위치나 셀 주소는 정하지 마세요. "
                      "확정된 항목만 사용하고 설명 없이 JSON을 반환하세요: "
                      '{\"client\": \"거래처\", \"values\": {\"recipient\": \"거래처\"}}. '
                      "값을 알 수 없는 항목과 수식 항목은 생략하세요. "
                       "품목이 여러 개면 item, quantity, unit_price, amount 값은 순서가 같은 배열로 반환하세요.")
        result = await completer(
            [{"role": "user", "content": asked.strip()}],
            additional_system_context=system + pattern + "\n\n양식 구조:\n"
            + json.dumps(structure, ensure_ascii=False)[:_MAX_REQUEST_CHARS * 8],
            attachments=(),
        )
    except Exception:
        return _error(502, "quote_template_mapping_failed")
    answer = result.get("answer") if isinstance(result, dict) else None
    confirmed = saved_form.get("mapping") if saved_form else None
    decided = (_confirmed_value_mapping(answer, confirmed, structure)
               if confirmed else _model_mapping(answer))
    if decided is None:
        return _error(502, "quote_template_mapping_failed")

    name = _filled_name(decided["client"], day)
    filled = await _lane_json(
        client, uid, method="POST", path="/files/" + lane_id + "/fill",
        payload={"mapping": decided["mapping"], "extend": decided["extend"], "filename": name},
    )
    if filled is None:
        return _error(502, "quote_template_fill_failed")
    if saved_form is not None and decided["extend"]:
        # The item-row pattern is what makes the second quote cheap; remember it
        # on the same stored form. A failed update never fails the fill itself.
        await _remember_item_rows(request, uid, saved_record, saved_form, decided["extend"])
    return _response({
        "ok": True,
        "filled_file_id": filled.get("file_id"),
        "filled_name": filled.get("name") or name,
        "template_name": template_name,
        "client": decided["client"],
        "mapping": decided["mapping"],
        "extend": decided["extend"],
        "form_id": saved_record.get("saved_skill_id") if saved_record else None,
    })


async def pc_quote_pdf(request: Request) -> Response:
    """Render a file-lane workbook belonging to the authenticated owner."""
    uid = _owner(request)
    if isinstance(uid, JSONResponse):
        return uid
    file_id = request.query_params.get("file_id", "")
    if re.fullmatch(r"file_[a-f0-9]{32}", file_id) is None:
        return _error(404, "quote_file_not_found")
    client = _cli(request)
    if client is None or getattr(client, "ready", False) is not True:
        return _error(503, "file_lane_unavailable")
    try:
        async with httpx.AsyncClient(
            transport=getattr(client, "_transport", None), timeout=100,
            follow_redirects=False, trust_env=False,
        ) as http:
            response = await http.get(
                client.origin + "/files/" + file_id + "/pdf",
                headers=_lane_headers(client, uid),
            )
        if response.status_code != 200 or not response.content.startswith(b"%PDF-"):
            return _error(503, "quote_pdf_unavailable")
    except Exception:
        return _error(503, "quote_pdf_unavailable")
    return Response(response.content, media_type="application/pdf", headers={
        "Cache-Control": "no-store, max-age=0",
        "Content-Disposition": 'attachment; filename="quote.pdf"',
    })
