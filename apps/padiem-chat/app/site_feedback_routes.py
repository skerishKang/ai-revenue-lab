"""Public site feedback: anonymous submit, CORS for the configured site, admin-only list."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .central_model_control_routes import _central_admin
from .feedback_store import FeedbackDailyLimit, FeedbackUnavailable
from .site_feedback_store import BODY_CHARS, SITE_FEEDBACK_ID, SITE_KEYS, STATUSES

SITE_ORIGINS = {
    'miraen-home': ('https://councillor-prototype-v2.pages.dev',),
}
_SCREEN_PATHS = frozenset({
    '/', '/index.html', '/about.html', '/about', '/activity.html', '/activity',
    '/policy.html', '/policy', '/media.html', '/media',
})
_NO_STORE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
             'X-Content-Type-Options': 'nosniff'}
_DAILY_LIMIT = 5
_SITE_DAILY_LIMIT = 200


def _response(payload, status=200, *, headers=None):
    return JSONResponse(payload, status_code=status, headers={**_NO_STORE, **(headers or {})})


def _error(code, status, *, headers=None):
    return _response({'ok': False, 'error': {'code': code}}, status, headers=headers)


def _store(request):
    return getattr(request.app.state, 'site_feedback_store', None)


def _now_ms():
    return int(time.time() * 1000)


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _cors(request, site):
    origin = request.headers.get('origin', '')
    allowed = SITE_ORIGINS.get(site, ())
    if origin not in allowed:
        return None
    return {'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'}


def _retry_after():
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return str(max(1, int((midnight - now).total_seconds())))


def _site_daily_limit(request):
    value = getattr(request.app.state.settings, 'site_feedback_daily_limit', _SITE_DAILY_LIMIT)
    try:
        return max(1, int(value))
    except Exception:
        return _SITE_DAILY_LIMIT


async def _body(request):
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        return None, _error('feedback_invalid_request', 415)
    try:
        raw = await read_bounded_request_body(request, max_bytes=BODY_CHARS * 12 + 16384)
        value = json.loads(raw.decode('utf-8'))
    except RequestBodyTooLarge:
        return None, _error('feedback_too_large', 413)
    except Exception:
        return None, _error('feedback_invalid_request', 400)
    if not isinstance(value, dict):
        return None, _error('feedback_invalid_request', 400)
    return value, None


def _screen(site, screen):
    if not isinstance(screen, dict) or set(screen) != {'url', 'width', 'height'}:
        raise ValueError('feedback_invalid_request')
    url, width, height = screen['url'], screen['width'], screen['height']
    if (not isinstance(url, str) or len(url) > 2048 or type(width) is not int or type(height) is not int
            or not 1 <= width <= 100000 or not 1 <= height <= 100000):
        raise ValueError('feedback_invalid_request')
    parsed = urlsplit(url)
    origin = parsed.scheme + '://' + parsed.netloc.rsplit('@', 1)[-1]
    if origin not in SITE_ORIGINS[site]:
        raise ValueError('feedback_invalid_request')
    path = parsed.path if parsed.path in _SCREEN_PATHS else '/'
    return {'url': origin + path, 'width': width, 'height': height}


def _rate_hash(request, site):
    forwarded = request.headers.get('x-forwarded-for', '')
    ip = (request.headers.get('cf-connecting-ip') or forwarded.split(',')[0].strip()
          or (request.client.host if request.client else ''))
    agent = request.headers.get('user-agent', '')
    day = _now_iso()[:10]
    return hashlib.sha256((ip + '\0' + agent + '\0' + site + '\0' + day).encode('utf-8')).hexdigest()


async def site_feedback(request):
    store = _store(request)
    if request.method == 'OPTIONS':
        # A browser's preflight carries no body, so the site cannot come from it.
        # The page posts to the bare endpoint; the preflight is allowed when the
        # Origin belongs to a registered site, and the POST below still checks
        # that its own site matches that Origin.
        origin = request.headers.get('origin', '')
        site = next((key for key, origins in SITE_ORIGINS.items() if origin in origins), '')
        headers = _cors(request, request.query_params.get('site', '') or site)
        if headers is None:
            return _error('feedback_invalid_request', 400)
        return _response({}, 204, headers=headers)
    if store is None:
        return _error('feedback_unavailable', 503)
    value, denied = await _body(request)
    if denied is not None:
        return denied
    site = value.get('site')
    headers = _cors(request, site) if isinstance(site, str) else None
    if headers is None:
        return _error('feedback_invalid_request', 400)
    if (set(value) - {'site', 'body', 'screen', 'rendered_at', 'honeypot'}
            or site not in SITE_KEYS or not isinstance(value.get('body'), str)
            or not value['body'].strip() or len(value['body']) > BODY_CHARS
            or any(ord(c) < 32 and c not in '\n\r\t' for c in value['body'])
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value['body'])
            or type(value.get('rendered_at')) is not int or value.get('honeypot') != ''):
        return _error('feedback_invalid_request', 400, headers=headers)
    try:
        screen = _screen(site, value.get('screen')) if 'screen' in value else None
    except Exception:
        return _error('feedback_invalid_request', 400, headers=headers)
    elapsed = _now_ms() - value['rendered_at']
    if elapsed < 1500 or elapsed > 6 * 60 * 60 * 1000:
        return _error('feedback_invalid_request', 400, headers=headers)
    try:
        record = await store.submit(
            site, value['body'], screen=screen, rate_hash=_rate_hash(request, site),
            daily_limit=_DAILY_LIMIT, site_daily_limit=_site_daily_limit(request),
            max_chars=BODY_CHARS, now=_now_iso())
        return _response({'ok': True, 'feedback': record.public()}, 201, headers=headers)
    except FeedbackDailyLimit:
        return _error('feedback_daily_limit', 429,
                      headers={**headers, 'Retry-After': _retry_after()})
    except FeedbackUnavailable:
        return _error('feedback_unavailable', 503, headers=headers)
    except ValueError:
        return _error('feedback_invalid_request', 400, headers=headers)


async def admin_site_feedback(request):
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    site, status = request.query_params.get('site', 'all'), request.query_params.get('status', 'all')
    cursor = request.query_params.get('cursor')
    if (set(request.query_params) - {'site', 'status', 'cursor'}
            or site not in SITE_KEYS | {'all'} or status not in STATUSES | {'all'}
            or (cursor and not SITE_FEEDBACK_ID.fullmatch(cursor))):
        return _error('feedback_invalid_request', 400)
    rows, next_cursor = await store.list_entries(
        site=None if site == 'all' else site, status=status, cursor=cursor)
    return _response({'ok': True, 'feedback': [row.public(admin=True) for row in rows],
                      'next_cursor': next_cursor, 'sites': sorted(SITE_KEYS)})


async def admin_site_feedback_status(request):
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
    if (not SITE_FEEDBACK_ID.fullmatch(feedback_id) or not value
            or set(value) - {'status', 'ops_memo'}
            or ('status' in value and 'ops_memo' in value)):
        return _error('feedback_invalid_request', 400)
    try:
        row = None
        if 'status' in value:
            row = await store.set_status(feedback_id, value['status'])
        if 'ops_memo' in value:
            row = await store.set_ops_memo(feedback_id, value['ops_memo'])
        if row is None:
            return _error('feedback_not_found', 404)
        record = await store.get_record(feedback_id)
        return _response({'ok': True, 'feedback': (record or row).public(admin=True)})
    except ValueError:
        return _error('feedback_invalid_request', 400)
    except Exception:
        return _error('feedback_unavailable', 503)