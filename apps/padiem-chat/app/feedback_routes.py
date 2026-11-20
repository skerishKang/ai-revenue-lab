"""Signed-in feedback and an inbox behind the existing Chat administrator guard."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .central_model_control_routes import _central_admin
from .feedback_store import BODY_CHARS, FEEDBACK_ID, STATUSES, FeedbackDailyLimit, FeedbackOwnerMissing
from .same_origin_guard import expected_browser_origins

_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}
_SCREEN_PATHS = frozenset({'/', '/chat', '/claw', '/settings', '/admin',
                          '/index.html', '/claw.html', '/settings.html', '/admin.html'})


def _response(payload, status=200, *, headers=None):
    return JSONResponse(payload, status_code=status, headers={**_NO_STORE, **(headers or {})})


def _error(code, status, *, headers=None):
    return _response({'ok': False, 'error': {'code': code}}, status, headers=headers)


def _owner(request):
    user_id = current_user_id(request) if auth_ready(request) else None
    if not user_id:
        return None, _error('authentication_required', 401)
    return user_id, None


def _store(request):
    return getattr(request.app.state, 'feedback_store', None)


def _limits(request):
    return {'body_chars': getattr(request.app.state.settings, 'feedback_max_chars', BODY_CHARS),
            'daily_submissions': getattr(request.app.state.settings, 'feedback_daily_limit', 10),
            'reply_chars': BODY_CHARS}

def _audit(request):
    return getattr(request.app.state, 'ops_audit_store', None)


async def _record_ops_action(request, *, action: str, target_id: str,
                             detail: dict) -> None:
    # #8035 ②: every administrator change (status·reply·AI-tester marking)
    # leaves who·when·what in the shared operations audit trail. The write
    # never breaks the caller's success path.
    actor = current_user_id(request) if auth_ready(request) else None
    audit = _audit(request)
    if audit is None or not actor:
        return
    try:
        await audit.append(actor_user_id=actor, action=action,
                           target_type='feedback', target_id=target_id,
                           detail=detail)
    except Exception:
        return


def _valid_text(value, limit):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not any(ord(c) < 32 and c not in '\n\r\t' for c in value)
            and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))


async def _body(request):
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        return None, _error('feedback_invalid_request', 415)
    try:
        # Accommodates JSON-escaped 4,000 supplementary Unicode characters.
        raw = await read_bounded_request_body(request, max_bytes=_limits(request)['body_chars'] * 12 + 16384)
        value = json.loads(raw.decode('utf-8'))
    except RequestBodyTooLarge:
        return None, _error('feedback_too_large', 413)
    except Exception:
        return None, _error('feedback_invalid_request', 400)
    if not isinstance(value, dict):
        return None, _error('feedback_invalid_request', 400)
    return value, None


def _screen(request, screen):
    if not isinstance(screen, dict) or set(screen) != {'url', 'width', 'height', 'app_version'}:
        raise ValueError('feedback_invalid_request')
    url, version = screen['url'], screen['app_version']
    if (not isinstance(url, str) or len(url) > 2048 or not isinstance(version, str)
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,79}', version) is None
            or any(type(screen[k]) is not int or not 1 <= screen[k] <= 100000 for k in ('width', 'height'))):
        raise ValueError('feedback_invalid_request')
    parsed = urlsplit(url)
    origin = parsed.scheme + '://' + parsed.netloc.rsplit('@', 1)[-1]
    if origin not in expected_browser_origins(request.app.state.settings):
        raise ValueError('feedback_invalid_request')
    # Only a fixed screen name survives. IDs and arbitrary path text do not.
    path = parsed.path if parsed.path in _SCREEN_PATHS else '/'
    return {'url': origin + path, 'width': screen['width'], 'height': screen['height'], 'app_version': version}


def _retry_after():
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return str(max(1, int((midnight - now).total_seconds())))


async def feedback(request):
    user_id, denied = _owner(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    if request.method == 'GET':
        cursor = request.query_params.get('cursor')
        if set(request.query_params) - {'cursor'} or (cursor and not FEEDBACK_ID.fullmatch(cursor)):
            return _error('feedback_invalid_request', 400)
        try:
            rows, next_cursor = await store.list_entries(user_id=user_id, cursor=cursor)
            unread = await store.unread_count(user_id)
            unread_replies = await store.unread_replies_count(user_id)
            await store.mark_replies_read(
                user_id, [row.id for row in rows if row.unread_ops_replies()])
            return _response({'ok': True, 'feedback': [row.public() for row in rows],
                              'next_cursor': next_cursor, 'unread_fixed_count': unread,
                              'unread_ops_replies_count': unread_replies,
                              'limits': _limits(request)})
        except Exception:
            return _error('feedback_unavailable', 503)
    value, denied = await _body(request)
    if denied is not None:
        return denied
    body = value.get('body')
    if set(value) - {'body', 'screen'} or not _valid_text(body, _limits(request)['body_chars']):
        return _error('feedback_invalid_request', 400)
    try:
        screen = _screen(request, value['screen']) if 'screen' in value else None
    except Exception:
        return _error('feedback_invalid_request', 400)
    try:
        row = await store.submit(user_id, body, screen=screen, daily_limit=_limits(request)['daily_submissions'],
                                 max_chars=_limits(request)['body_chars'])
        # #8105: 알림은 저장 성공 뒤에 부른다. 실패해도 접수는 그대로 성공한다.
        from .ops_alert_delivery import enqueue_and_deliver
        await enqueue_and_deliver(request, kind='product_feedback',
                                  target_id=row.id, label='chat')
        return _response({'ok': True, 'feedback': row.public()}, 201)
    except FeedbackDailyLimit:
        return _error('feedback_daily_limit', 429, headers={'Retry-After': _retry_after()})
    except FeedbackOwnerMissing:
        return _error('authentication_required', 401)
    except Exception:
        return _error('feedback_unavailable', 503)


async def feedback_read(request):
    user_id, denied = _owner(request)
    if denied is not None:
        return denied
    value, denied = await _body(request)
    if denied is not None:
        return denied
    feedback_id = request.path_params.get('feedback_id', '')
    version = value.get('fixed_version')
    if (not FEEDBACK_ID.fullmatch(feedback_id) or set(value) != {'fixed_version'}
            or type(version) is not int or not 1 <= version <= 2**53 - 1):
        return _error('feedback_invalid_request', 400)
    try:
        row = await _store(request).mark_read(user_id, feedback_id, version)
        if row is None:
            return _error('feedback_not_found', 404)
        record = await _store(request).get_record(feedback_id, user_id=user_id)
        return _response({'ok': True, 'feedback': (record or row).public()})
    except Exception:
        return _error('feedback_unavailable', 503)


async def feedback_reply(request):
    user_id, denied = _owner(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    value, denied = await _body(request)
    if denied is not None:
        return denied
    feedback_id = request.path_params.get('feedback_id', '')
    body = value.get('body')
    if (not FEEDBACK_ID.fullmatch(feedback_id) or set(value) != {'body'}
            or not _valid_text(body, BODY_CHARS)):
        return _error('feedback_invalid_request', 400)
    try:
        reply = await store.add_reply(feedback_id, 'user', body, user_id=user_id)
        if reply is None:
            return _error('feedback_not_found', 404)
        record = await store.get_record(feedback_id, user_id=user_id)
        return _response({'ok': True, 'reply': reply.public(),
                          'feedback': record.public() if record is not None else None}, 201)
    except Exception:
        return _error('feedback_unavailable', 503)


async def admin_feedback(request):
    # Reuse the existing guard verbatim; no new role, identity claim or fallback.
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    status, cursor = request.query_params.get('status', 'all'), request.query_params.get('cursor')
    if (set(request.query_params) - {'status', 'cursor'} or status not in STATUSES | {'all'}
            or (cursor and not FEEDBACK_ID.fullmatch(cursor))):
        return _error('feedback_invalid_request', 400)
    try:
        store = _store(request)
        rows, next_cursor = await store.list_entries(status=status, cursor=cursor)
        intros = {}
        ai_rows = [row for row in rows if getattr(row, 'is_ai_tester', False)]
        if ai_rows:
            intros = await store.intro_store().get_many([row.user_id for row in ai_rows])
        items = []
        for row in rows:
            item = row.public(admin=True)
            if getattr(row, 'is_ai_tester', False) and row.user_id in intros:
                item['sender_intro'] = intros[row.user_id]
            items.append(item)
        return _response({'ok': True, 'feedback': items,
                          'next_cursor': next_cursor, 'limits': _limits(request)})
    except Exception:
        return _error('feedback_unavailable', 503)


async def admin_feedback_reply(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    value, denied = await _body(request)
    if denied is not None:
        return denied
    feedback_id = request.path_params.get('feedback_id', '')
    body = value.get('body')
    if (not FEEDBACK_ID.fullmatch(feedback_id) or set(value) != {'body'}
            or not _valid_text(body, BODY_CHARS)):
        return _error('feedback_invalid_request', 400)
    try:
        reply = await store.add_reply(feedback_id, 'ops', body)
        if reply is None:
            return _error('feedback_not_found', 404)
        record = await store.get_record(feedback_id)
        await _record_ops_action(request, action='feedback_reply',
                                 target_id=feedback_id,
                                 detail={'reply_chars': len(body)})
        return _response({'ok': True, 'reply': reply.public(),
                          'feedback': record.public(admin=True) if record is not None else None}, 201)
    except Exception:
        return _error('feedback_unavailable', 503)


async def admin_feedback_ai_tester(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    value, denied = await _body(request)
    if denied is not None:
        return denied
    feedback_id = request.path_params.get('feedback_id', '')
    enabled = value.get('ai_tester')
    if (not FEEDBACK_ID.fullmatch(feedback_id) or set(value) != {'ai_tester'}
            or type(enabled) is not bool):
        return _error('feedback_invalid_request', 400)
    try:
        row = await store.set_ai_tester(feedback_id, enabled)
        await _record_ops_action(request, action='feedback_ai_tester',
                                 target_id=feedback_id, detail={'enabled': enabled})
        return (_response({'ok': True, 'feedback': row.public(admin=True)}) if row is not None
                else _error('feedback_not_found', 404))
    except Exception:
        return _error('feedback_unavailable', 503)


async def admin_feedback_status(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    value, denied = await _body(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    feedback_id, status = request.path_params.get('feedback_id', ''), value.get('status')
    if (not FEEDBACK_ID.fullmatch(feedback_id) or set(value) != {'status'}
            or not isinstance(status, str) or status not in STATUSES):
        return _error('feedback_invalid_request', 400)
    try:
        row = await store.set_status(feedback_id, status)
        if row is None:
            return _error('feedback_not_found', 404)
        record = await store.get_record(feedback_id)
        await _record_ops_action(request, action='feedback_status',
                                 target_id=feedback_id, detail={'to': status})
        return (_response({'ok': True, 'feedback': record.public(admin=True)}) if record is not None
                else _error('feedback_not_found', 404))
    except Exception:
        return _error('feedback_unavailable', 503)
