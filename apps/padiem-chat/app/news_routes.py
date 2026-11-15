"""Signed-in '새 소식' routes: the recent list (which marks it seen) and the
sidebar unseen counter, which must not mark anything."""
from __future__ import annotations

from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .news_store import NEWS_PAGE

_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}


def _response(payload, status=200):
    return JSONResponse(payload, status_code=status, headers=_NO_STORE)


def _error(code, status):
    return _response({'ok': False, 'error': {'code': code}}, status)


def _owner(request):
    user_id = current_user_id(request) if auth_ready(request) else None
    if not user_id:
        return None, _error('authentication_required', 401)
    return user_id, None


def _store(request):
    return getattr(request.app.state, 'news_store', None)


async def news(request):
    user_id, denied = _owner(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('news_unavailable', 503)
    if request.query_params:
        return _error('news_invalid_request', 400)
    try:
        rows = await store.list_recent(NEWS_PAGE)
        # The count is computed before the screen-open marks the list seen, so
        # the very first look still says how many items were waiting.
        unread = await store.unread_count(user_id)
        await store.mark_seen(user_id)
        return _response({'ok': True, 'news': [row.public() for row in rows],
                          'unread_count': unread})
    except Exception:
        return _error('news_unavailable', 503)


async def news_unread(request):
    user_id, denied = _owner(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('news_unavailable', 503)
    if request.query_params:
        return _error('news_invalid_request', 400)
    try:
        return _response({'ok': True, 'unread_count': await store.unread_count(user_id)})
    except Exception:
        return _error('news_unavailable', 503)
