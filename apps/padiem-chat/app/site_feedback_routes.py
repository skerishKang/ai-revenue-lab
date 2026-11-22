"""Public site feedback: anonymous submit, CORS for the configured site, admin-only list."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .central_model_control_routes import _central_admin
from .feedback_store import FeedbackDailyLimit, FeedbackUnavailable
from .site_feedback_store import (BODY_CHARS, EXTERNAL_CATEGORIES, EXTERNAL_STATUSES,
                                 INGEST_EVENTS, SITE_FEEDBACK_ID, SITE_KEYS, STATUSES)

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
# #7690: Lovetree 서버-서버 수신 계약 (받는 쪽). 브라우저 CORS·공개 origin 없이
# HMAC 서명만으로 받는다. 시각은 밀리초 문자열, 서명은 sha256=<hex>, 메시지는
# 시각 + '\n' + 사이트 + '\n' + 본문 원문 바이트, 허용 시각 차이는 5분이다.
_INGEST_SITE = 'lovetree'
_INGEST_FIELDS = frozenset({'event', 'feedbackId', 'body', 'status', 'append',
                            'isAiCustomer', 'accountSubjectId', 'category',
                            'title', 'createdAt'})
_INGEST_MAX_BYTES = 65536
_SIGNATURE_WINDOW_MS = 5 * 60 * 1000
_TIMESTAMP = re.compile(r'[0-9]{1,20}\Z')
_SIGNATURE = re.compile(r'sha256=[0-9a-f]{64}\Z')


def _response(payload, status=200, *, headers=None):
    return JSONResponse(payload, status_code=status, headers={**_NO_STORE, **(headers or {})})


def _error(code, status, *, headers=None):
    return _response({'ok': False, 'error': {'code': code}}, status, headers=headers)


def _journal_received(site, feedback_id) -> None:
    # #7690: one receipt line for the ops journal — the site key and the
    # feedback id only, never the body, the screen or anything user-controlled.
    print(f"site_feedback_received site={site} id={feedback_id}", flush=True)


def _journal_rejected(site, code) -> None:
    # #7690: a refusal journals the registered site key and the closed reason
    # code only; without a registered site nothing is attributed or printed.
    if not isinstance(site, str) or site not in SITE_KEYS:
        return
    print(f"site_feedback_rejected site={site} reason={code}", flush=True)


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
        # A 204 carries no body; a JSON '{}' made the server log a length error.
        return Response(status_code=204, headers={**_NO_STORE, **headers})
    if store is None:
        return _error('feedback_unavailable', 503)
    value, denied = await _body(request)
    if denied is not None:
        return denied
    site = value.get('site')
    headers = _cors(request, site) if isinstance(site, str) else None
    if headers is None:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400)
    if (set(value) - {'site', 'body', 'screen', 'rendered_at', 'honeypot'}
            or site not in SITE_KEYS or not isinstance(value.get('body'), str)
            or not value['body'].strip() or len(value['body']) > BODY_CHARS
            or any(ord(c) < 32 and c not in '\n\r\t' for c in value['body'])
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value['body'])
            or type(value.get('rendered_at')) is not int or value.get('honeypot') != ''):
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400, headers=headers)
    try:
        screen = _screen(site, value.get('screen')) if 'screen' in value else None
    except Exception:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400, headers=headers)
    elapsed = _now_ms() - value['rendered_at']
    if elapsed < 1500 or elapsed > 6 * 60 * 60 * 1000:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400, headers=headers)
    try:
        record = await store.submit(
            site, value['body'], screen=screen, rate_hash=_rate_hash(request, site),
            daily_limit=_DAILY_LIMIT, site_daily_limit=_site_daily_limit(request),
            max_chars=BODY_CHARS, now=_now_iso())
        public = record.public()
        _journal_received(site, public['id'])
        # #8105: 알림은 저장 성공 뒤. 실패해도 접수는 그대로 성공한다.
        from .ops_alert_delivery import enqueue_and_deliver
        await enqueue_and_deliver(request, kind='site_feedback',
                                  target_id=public['id'], label=site)
        return _response({'ok': True, 'feedback': public}, 201, headers=headers)
    except FeedbackDailyLimit:
        _journal_rejected(site, 'feedback_daily_limit')
        return _error('feedback_daily_limit', 429,
                      headers={**headers, 'Retry-After': _retry_after()})
    except FeedbackUnavailable:
        _journal_rejected(site, 'feedback_unavailable')
        return _error('feedback_unavailable', 503, headers=headers)
    except ValueError:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400, headers=headers)


def _ingest_secrets(request):
    settings = getattr(request.app.state, 'settings', None)
    secrets = []
    for name in ('site_feedback_secret_lovetree', 'site_feedback_secret_lovetree_previous'):
        value = getattr(settings, name, None)
        if isinstance(value, str) and value:
            secrets.append(value)
    return tuple(secrets)


def _ingest_text(value, limit, *, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit:
        return False
    if not allow_empty and not value.strip():
        return False
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        return False
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        return False
    return True


def _ingest_payload_valid(value):
    if not isinstance(value, dict) or set(value) != _INGEST_FIELDS:
        return False
    event = value['event']
    if event not in INGEST_EVENTS:
        return False
    if type(value['feedbackId']) is not int or value['feedbackId'] < 1:
        return False
    body = value['body']
    if event == 'new':
        if not _ingest_text(body, BODY_CHARS):
            return False
    elif event == 'append':
        if not _ingest_text(body, 4000):
            return False
    elif not _ingest_text(body, BODY_CHARS, allow_empty=True):
        return False
    if value['status'] not in EXTERNAL_STATUSES:
        return False
    append = value['append']
    if event == 'append':
        if not _ingest_text(append, 4000):
            return False
    elif append is not None:
        return False
    if type(value['isAiCustomer']) is not bool:
        return False
    account = value['accountSubjectId']
    if account is not None and not _ingest_text(account, 256):
        return False
    category = value['category']
    if event == 'new':
        if category not in EXTERNAL_CATEGORIES:
            return False
    elif category not in EXTERNAL_CATEGORIES | {''}:
        return False
    if not _ingest_text(value['title'], 120, allow_empty=True):
        return False
    return _ingest_text(value['createdAt'], 64)


async def site_feedback_ingest(request):
    """#7690: Lovetree 서버-서버 수신. 브라우저 CORS·공개 origin 없이 HMAC만 본다."""
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    site = request.headers.get('x-lt-site', '')
    if site != _INGEST_SITE:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400)
    timestamp = request.headers.get('x-lt-timestamp', '')
    signature = request.headers.get('x-lt-signature', '')
    if not _TIMESTAMP.fullmatch(timestamp or '') or not signature:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400)
    secrets = _ingest_secrets(request)
    if not secrets:
        _journal_rejected(site, 'feedback_unavailable')
        return _error('feedback_unavailable', 503)
    if abs(_now_ms() - int(timestamp)) > _SIGNATURE_WINDOW_MS:
        _journal_rejected(site, 'feedback_invalid_signature')
        return _error('feedback_invalid_signature', 401)
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 415)
    try:
        raw = await read_bounded_request_body(request, max_bytes=_INGEST_MAX_BYTES)
    except RequestBodyTooLarge:
        return _error('feedback_too_large', 413)
    except Exception:
        return _error('feedback_invalid_request', 400)
    if not _SIGNATURE.fullmatch(signature):
        _journal_rejected(site, 'feedback_invalid_signature')
        return _error('feedback_invalid_signature', 401)
    presented = signature[len('sha256='):]
    message = timestamp.encode('utf-8') + b'\n' + site.encode('utf-8') + b'\n' + raw
    if not any(hmac.compare_digest(
            hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest(), presented)
            for secret in secrets):
        _journal_rejected(site, 'feedback_invalid_signature')
        return _error('feedback_invalid_signature', 401)
    try:
        value = json.loads(raw.decode('utf-8'))
    except Exception:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400)
    if not _ingest_payload_valid(value):
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400)
    try:
        result = await store.ingest_lovetree(
            external_feedback_id=value['feedbackId'], event=value['event'], body=value['body'],
            status=value['status'], append=value['append'], is_ai_customer=value['isAiCustomer'],
            account_subject_id=value['accountSubjectId'], category=value['category'],
            title=value['title'], created_at=value['createdAt'], now=_now_iso())
    except FeedbackUnavailable:
        _journal_rejected(site, 'feedback_unavailable')
        return _error('feedback_unavailable', 503)
    except ValueError:
        _journal_rejected(site, 'feedback_invalid_request')
        return _error('feedback_invalid_request', 400)
    if result is None:
        _journal_rejected(site, 'feedback_not_found')
        return _error('feedback_not_found', 404)
    record, created, duplicate = result
    public = record.public(admin=True)
    if created:
        _journal_received(site, public['id'])
        # #8105: 알림은 저장 성공 뒤. 실패해도 접수는 그대로 성공한다.
        from .ops_alert_delivery import enqueue_and_deliver
        await enqueue_and_deliver(request, kind='site_feedback',
                                  target_id=public['id'], label=site)
        return _response({'ok': True, 'feedback': public}, 201)
    payload = {'ok': True, 'feedback': public}
    if duplicate:
        payload['duplicate'] = True
    return _response(payload, 200)


async def _site_access(request):
    """Resolve who may read site feedback: 'central', 'site', or denied.

    The central verdict is unchanged. A signed-in account that is not central
    may still be a designated site administrator (migration 119); the site
    list always comes from the server's own table, never from the request.
    An account with no site fails closed to the existing non-admin verdict.
    """
    denied = await _central_admin(request)
    if denied is None:
        return 'central', None, None
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return None, None, denied
    authorizer = getattr(request.app.state, 'site_feedback_admin_authorizer', None)
    sites_for = getattr(authorizer, 'sites_for', None) if authorizer is not None else None
    if not callable(sites_for):
        return None, None, denied
    try:
        found = await sites_for(user_id=owner)
    except Exception:
        return None, None, _error('feedback_unavailable', 503)
    allowed = frozenset(value for value in (found or ())
                        if isinstance(value, str) and value in SITE_KEYS)
    if not allowed:
        return None, None, denied
    return 'site', allowed, None


async def admin_site_feedback(request):
    role, sites, denied = await _site_access(request)
    if denied is not None:
        return denied
    store = _store(request)
    if store is None:
        return _error('feedback_unavailable', 503)
    site, status = ((request.query_params.get('site', 'all') or 'all'),
                    request.query_params.get('status', 'all'))
    cursor = request.query_params.get('cursor')
    if (set(request.query_params) - {'site', 'status', 'cursor'}
            or site not in SITE_KEYS | {'all'} or status not in STATUSES | {'all'}
            or (cursor and not SITE_FEEDBACK_ID.fullmatch(cursor))):
        return _error('feedback_invalid_request', 400)
    if role == 'site' and site != 'all' and site not in sites:
        # Another site is never revealed, including through the site filter.
        return _error('feedback_not_found', 404)
    rows, next_cursor = await store.list_entries(
        site=None if site == 'all' else site,
        sites=sites if role == 'site' and site == 'all' else None,
        status=status, cursor=cursor)
    return _response({'ok': True, 'feedback': [row.public(admin=True) for row in rows],
                      'next_cursor': next_cursor,
                      'sites': sorted(sites) if role == 'site' else sorted(SITE_KEYS)})


async def admin_site_feedback_status(request):
    role, sites, denied = await _site_access(request)
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
        if role == 'site':
            # The feedback's stored site decides access; the request never
            # names it, and another site is answered as not found.
            row = await store.get_record(feedback_id)
            if row is None or row.site not in sites:
                return _error('feedback_not_found', 404)
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