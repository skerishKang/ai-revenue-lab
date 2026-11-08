from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .history import MAX_CONVERSATION_SEARCH_QUERY_CHARS, HistoryPinUnavailable, HistoryStore, validate_conversation_id
from .history import PRODUCT_SCOPE_CHAT
from .history import MAX_HISTORY_TITLE_CHARS

# #7175: a rename/pin body is two short fields, never an attachment.
MAX_CONVERSATION_UPDATE_BODY_BYTES = 4096


def _history_unavailable() -> JSONResponse:
    return JSONResponse({"error": {"code": "history_unavailable", "message": "저장된 대화를 현재 사용할 수 없습니다."}}, status_code=503)


async def api_conversations(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _history_unavailable()
    uid = current_user_id(request)
    if uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    store: HistoryStore = request.app.state.history_store
    try:
        conversations = await store.list_conversations(uid, product_scope=PRODUCT_SCOPE_CHAT)
    except Exception:
        return _history_unavailable()
    return JSONResponse({"conversations": conversations})


async def api_conversation_search(request: Request) -> JSONResponse:
    """#4471: owner-scoped search over the signed-in user's own conversations.

    Read-only. Same auth and history-availability contract as the list route.
    The query is bounded and bound as a parameter by the store.
    """
    if not auth_ready(request):
        return _history_unavailable()
    uid = current_user_id(request)
    if uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    query = request.query_params.get("q", "")
    if not isinstance(query, str) or not query.strip():
        return JSONResponse({"conversations": [], "query": ""})
    if len(query) > MAX_CONVERSATION_SEARCH_QUERY_CHARS * 4:
        return JSONResponse(
            {"error": {"code": "query_too_long", "message": "검색어가 너무 깁니다."}},
            status_code=400,
        )
    store: HistoryStore = request.app.state.history_store
    try:
        conversations = await store.search_conversations(uid, query, product_scope=PRODUCT_SCOPE_CHAT)
    except Exception:
        return _history_unavailable()
    return JSONResponse({"conversations": conversations, "query": query.strip()[:MAX_CONVERSATION_SEARCH_QUERY_CHARS]})


async def api_conversation_update(request: Request) -> JSONResponse:
    """#7175: rename and/or pin one conversation the signed-in owner owns.

    Unknown ids, malformed ids and another account's conversation all answer
    404 with the same body, so the route never reveals whether a foreign
    conversation exists. The title is collapsed and bounded to the store's
    1..80 ceiling before it reaches the UPDATE.
    """
    if not auth_ready(request):
        return _history_unavailable()
    uid = current_user_id(request)
    if uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    try:
        cid = validate_conversation_id(request.path_params.get("conversation_id"))
    except ValueError:
        cid = None
    if cid is None:
        return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_CONVERSATION_UPDATE_BODY_BYTES)
    except RequestBodyTooLarge:
        return JSONResponse(
            {"error": {"code": "conversation_body_too_large", "message": "요청이 너무 큽니다."}},
            status_code=413,
        )
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raw = None
    if not isinstance(raw, dict) or not raw or set(raw) - {"title", "pinned"}:
        return JSONResponse(
            {"error": {"code": "conversation_body_invalid", "message": "지원하지 않는 대화 요청 항목이 있습니다."}},
            status_code=400,
        )
    title = None
    if "title" in raw:
        if not isinstance(raw["title"], str):
            return JSONResponse(
                {"error": {"code": "conversation_title_invalid", "message": "대화 제목 형식이 올바르지 않습니다."}},
                status_code=400,
            )
        title = " ".join(raw["title"].split())
        if not 1 <= len(title) <= MAX_HISTORY_TITLE_CHARS:
            return JSONResponse(
                {"error": {"code": "conversation_title_invalid", "message": "대화 제목은 1자 이상 80자 이하로 입력해 주세요."}},
                status_code=400,
            )
    pinned = None
    if "pinned" in raw:
        if not isinstance(raw["pinned"], bool):
            return JSONResponse(
                {"error": {"code": "conversation_pin_invalid", "message": "고정 값은 true 또는 false여야 합니다."}},
                status_code=400,
            )
        pinned = raw["pinned"]
    store: HistoryStore = request.app.state.history_store
    try:
        updated = await store.update_conversation(
            uid, cid, product_scope=PRODUCT_SCOPE_CHAT, title=title, pinned=pinned,
        )
    except HistoryPinUnavailable:
        # The database has not applied migration 104. Every existing read still
        # works; only the pin write refuses, with its own reason.
        return JSONResponse(
            {"error": {"code": "conversation_pin_unavailable", "message": "대화 고정을 아직 사용할 수 없습니다."}},
            status_code=503,
        )
    except Exception:
        return _history_unavailable()
    if updated is None:
        return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
    return JSONResponse({"updated": True, "conversation": updated})


async def api_conversation_detail(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _history_unavailable()
    uid = current_user_id(request)
    if uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    try:
        cid = validate_conversation_id(request.path_params.get("conversation_id"))
    except ValueError:
        cid = None
    if cid is None:
        return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
    store: HistoryStore = request.app.state.history_store
    if request.method == "DELETE":
        try:
            deleted = await store.delete_conversation(uid, cid, product_scope=PRODUCT_SCOPE_CHAT)
        except Exception:
            return _history_unavailable()
        if not deleted:
            return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
        return JSONResponse({"deleted": True, "conversation_id": cid})
    try:
        conversation = await store.get_conversation(uid, cid, product_scope=PRODUCT_SCOPE_CHAT)
    except Exception:
        return _history_unavailable()
    if conversation is None:
        return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
    return JSONResponse({"conversation": conversation})
