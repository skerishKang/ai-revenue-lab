from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .history import MAX_CONVERSATION_SEARCH_QUERY_CHARS, HistoryStore, validate_conversation_id
from .history import PRODUCT_SCOPE_CHAT


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
