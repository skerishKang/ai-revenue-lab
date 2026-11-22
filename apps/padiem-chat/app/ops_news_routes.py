"""#8035 ④: administer public news through the same publishing service as the CLI."""
from __future__ import annotations

import json

from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth_routes import auth_ready, current_user_id
from .central_model_control_routes import _central_admin
from .feedback_store import FeedbackUnavailable
from .news_publish import NewsPublishError, write_news
from .news_store import NEWS_PAGE, NewsUnavailable

_HEADERS = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
            'X-Content-Type-Options': 'nosniff'}
_REQUIRED = {'version', 'kind', 'title', 'detail', 'source'}
_KEYS = _REQUIRED | {'feedback'}
_ERROR_STATUS = {'NEWS_NOT_FOUND': 404, 'FEEDBACK_NOT_FOUND': 404,
                 'FEEDBACK_ALREADY_LINKED': 409, 'FEEDBACK_LINK_FAILED': 503,
                 'NEWS_STORE_REFUSED': 503, 'NEWS_STORE_UNAVAILABLE': 503,
                 'FEEDBACK_STORE_UNAVAILABLE': 503}


def _response(body, status=200):
    return JSONResponse(body, status_code=status, headers=_HEADERS)


def _error(code, status=None, **extra):
    return _response({'ok': False, 'error': {'code': code}, **extra},
                     status or _ERROR_STATUS.get(code, 400))


def _context(request):
    state = request.app.state
    return (getattr(state, 'news_store', None),
            getattr(state, 'feedback_store', None),
            getattr(state, 'ops_audit_store', None),
            current_user_id(request) if auth_ready(request) else None)


async def _body(request):
    try:
        data = json.loads(await request.body())
    except (ValueError, TypeError):
        raise NewsPublishError('NEWS_INVALID_REQUEST') from None
    if not isinstance(data, dict) or set(data) - _KEYS or not _REQUIRED <= set(data):
        raise NewsPublishError('NEWS_INVALID_REQUEST')
    return data


async def _public_with_links(store, rows):
    links = await store.linked_feedback([row.number for row in rows])
    return [{**row.public(), 'feedback_ids': links[row.number]} for row in rows]


async def admin_news_list(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store, _, audit, actor = _context(request)
    if store is None or audit is None:
        return _error('NEWS_STORE_UNAVAILABLE')
    if request.query_params:
        return _error('NEWS_INVALID_REQUEST')
    try:
        rows = await _public_with_links(store, await store.list_recent(NEWS_PAGE))
    except NewsUnavailable:
        return _error('NEWS_STORE_UNAVAILABLE')
    await audit.append(actor_user_id=actor, action='news_view', target_type='news',
                       target_id='list', detail={'count': len(rows)})
    return _response({'ok': True, 'news': rows})


async def _write(request, number=None):
    store, feedback, audit, actor = _context(request)
    if store is None or audit is None:
        return _error('NEWS_STORE_UNAVAILABLE')
    if request.query_params:
        return _error('NEWS_INVALID_REQUEST')
    try:
        data = await _body(request)
        result = await write_news(store, feedback, **data, number=number,
                                  audit=audit, actor=actor)
    except NewsPublishError as exc:
        return _error(exc.code)
    except (NewsUnavailable, FeedbackUnavailable):
        return _error('NEWS_STORE_UNAVAILABLE')
    if result.record is None:
        return _error(result.error)
    # A write that could not finish its links still returns the saved number.
    # The UI can continue editing the saved item without creating a duplicate.
    try:
        row = (await _public_with_links(store, [result.record]))[0]
    except NewsUnavailable:
        return _error('NEWS_STORE_UNAVAILABLE', news=result.record.public())
    if result.error:
        return _error(result.error, news=row)
    return _response({'ok': True, 'news': row}, 201 if number is None else 200)


async def admin_news_create(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    return await _write(request)


async def admin_news_update(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    raw = request.path_params.get('number', '')
    if not isinstance(raw, int) or raw < 1:
        return _error('NEWS_NUMBER_INVALID')
    return await _write(request, raw)


def register_ops_news_routes(routes: list) -> None:
    routes.extend([
        Route('/api/admin/news', admin_news_list, methods=['GET']),
        Route('/api/admin/news', admin_news_create, methods=['POST']),
        Route('/api/admin/news/{number:int}', admin_news_update, methods=['PATCH']),
    ])
