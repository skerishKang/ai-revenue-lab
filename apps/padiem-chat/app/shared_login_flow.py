"""Opt-in OAuth authorization-code flow for Chat's common login.

This module is not mounted by default.  It depends on #6267 and deliberately
delegates session creation until the Worker session integration is supplied.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

from .auth import SESSION_COOKIE, decode_session_claims
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from .session_revocation_guard import session_verdict

from .shared_auth_compare_flow import AUTH, TOKEN_URL, ComparisonFlow, _await, _b64, _encoded, _un64

CALLBACK = 'https://chat.padiem.net/auth/shared/callback'
STATE_COOKIE = '__Host-padiem-shared-state'
ACCESS_COOKIE = '__Host-padiem-shared-access'
REFRESH_COOKIE = 'padiem_shared_refresh'
MARKER_COOKIE = '__Host-padiem-shared-marker'
LOGIN_RETURN_COOKIE = '__Host-padiem-login-return'
LOGIN_RETURN_MAX_CHARS = 3000
REFRESH_PATH = '/auth/shared'
ACCESS_SECONDS = 15 * 60
REFRESH_SECONDS = 30 * 24 * 60 * 60

logger = logging.getLogger(__name__)


def parse_extra_origins(raw) -> tuple[str, ...]:
    """Reviewed extra hosts that may run this login (#6850).

    A comma-separated configuration value, https only, origin only. Anything
    malformed is dropped rather than guessed at: a host that is not listed here
    can never influence the callback or satisfy the origin checks.
    """
    if raw is None:
        return ()
    text = raw.decode('utf-8', 'ignore') if isinstance(raw, (bytes, bytearray)) else str(raw)
    origins: list[str] = []
    for part in text.split(','):
        value = part.strip().rstrip('/')
        if not value:
            continue
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment):
            continue
        origin = 'https://' + parsed.netloc
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)

# Only these literal codes may reach logs. Exceptions (including RPC errors)
# can contain credentials, response bodies or profile values; never stringify
# them or attach a traceback. Follow explicit causes to retain the authority's
# reason through SharedAuthUnavailable without exposing its message.
_FINISH_FAILURE_CODES = frozenset({
    'invalid_flow', 'invalid_cookie', 'invalid_state', 'invalid_exchange', 'invalid_grant',
    'state_cookie_missing', 'state_expired', 'state_mismatch',
    'unknown_account', 'invalid_session_response', 'invalid_es256_signature',
    'invalid_key', 'invalid_token_endpoint', 'exchange_failed',
    'exchange_response_too_large', 'exchange_invalid_response',
    'invalid_shared_credential', 'invalid_verified_claims', 'missing_product_link',
    'reverse_lookup_failed', 'reverse_lookup_invalid', 'shared_auth_failed',
    'invalid_encoding', 'invalid_token', 'invalid_header', 'unknown_key',
    'invalid_signature', 'invalid_claims', 'token_not_yet_valid', 'token_expired',
    'jwks_unavailable', 'jwks_too_large',
    'invalid_jwks', 'control_plane_identity_unavailable', 'control_plane_rpc_invalid',
    'canonical_product_identity_link_not_found',
    'canonical_product_identity_link_not_active', 'identity_authority_storage_error',
    'identity_authority_product_mismatch', 'profile_store_unavailable',
    'service_rpc_unauthorized', 'service_rpc_forbidden', 'service_rpc_not_found',
    'service_rpc_replay_rejected', 'service_rpc_rate_limited', 'service_rpc_http_failed',
    'invalid_profile_response', 'profile_account_mismatch', 'invalid_profile',
    'legacy_account_conflict',
})


# #6922: a callback that does not belong to a login this host started. No state
# cookie (started on another host, older than the 10-minute window, or cookies
# blocked), a cookie this host did not sign, an expired or mismatched state: the
# browser's flow is wrong, not this host, so the answer is 400 with a restart
# link instead of 503 (which the patrol counted as an outage and the user read
# as "service unavailable"). Anything else in the stage stays a host failure.
_FLOW_RESTART_CODES = frozenset({
    'invalid_flow', 'state_cookie_missing', 'invalid_cookie', 'state_expired',
    'state_mismatch', 'invalid_state',
})

# A one-time authorization code rejected by the authority must be retried by
# starting a fresh login. Other token-exchange failures remain retryable 503s.
_EXCHANGE_RESTART_CODES = frozenset({'invalid_grant'})

RESTART_LOGIN_PATH = '/auth/shared/start'

_RESTART_PAGE = (
    '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="robots" content="noindex"><title>로그인을 다시 시작해 주세요</title>'
    '<style>body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;'
    'display:flex;min-height:100vh;align-items:center;justify-content:center;'
    'background:#f6f6f7;color:#1c1c1e}main{max-width:28rem;margin:1rem;padding:2rem;'
    'background:#fff;border-radius:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}'
    'h1{font-size:1.25rem;margin:0 0 .75rem}p{margin:.5rem 0;line-height:1.55}'
    'a.button{display:inline-block;margin-top:1rem;padding:.6rem 1.1rem;border-radius:8px;'
    'background:#1c1c1e;color:#fff;text-decoration:none}code{font-size:.8rem;color:#6e6e73}'
    '</style></head><body><main>'
    '<h1>로그인을 처음부터 다시 시작해 주세요</h1>'
    '<p>이 로그인 요청은 이 주소에서 시작한 로그인과 맞지 않습니다. 로그인 창을 연 지 '
    '10분이 지났거나, 다른 주소에서 시작했거나, 브라우저가 쿠키를 막은 경우입니다.</p>'
    '<a class="button" href="' + RESTART_LOGIN_PATH + '">다시 로그인</a>'
    '<p><code>{code}</code></p></main></body></html>'
)


def _restart_login_response(code, headers):
    """The 400 answer for a mismatched callback: what happened, and the way back in."""
    return HTMLResponse(_RESTART_PAGE.replace('{code}', code), status_code=400, headers=headers)


_RETRY_LATER_STYLE = (
    'body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;'
    'display:flex;min-height:100vh;align-items:center;justify-content:center;'
    'background:#f6f6f7;color:#1c1c1e}main{max-width:28rem;margin:1rem;padding:2rem;'
    'background:#fff;border-radius:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}'
    'h1{font-size:1.25rem;margin:0 0 .75rem}p{margin:.5rem 0;line-height:1.55}'
    'a.button{display:inline-block;margin-top:1rem;padding:.6rem 1.1rem;border-radius:8px;'
    'background:#1c1c1e;color:#fff;text-decoration:none}'
)

#: #7699: a browser that lands on the callback during an authority blip used to
#: read raw JSON. The status stays 503 (retryable); only the body becomes a page.
_RETRY_LATER_PAGES = {
    'ko': ('로그인을 마치지 못했습니다',
           '잠시 후 다시 시도해 주세요. 계속되면 로그인을 처음부터 다시 시작해 주세요.',
           '다시 로그인'),
    'en': ("We couldn't finish signing you in",
           'Please try again shortly. If it keeps happening, start the sign-in again.',
           'Try again'),
}


def _retry_later_page(request) -> str:
    language = (request.headers.get('accept-language') or '').split(',')[0].strip().lower()
    english = language.startswith('en')
    title, body, action = _RETRY_LATER_PAGES['en' if english else 'ko']
    return ('<!doctype html><html lang="' + ('en' if english else 'ko') + '">'
            '<head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="robots" content="noindex"><title>' + title + '</title>'
            '<style>' + _RETRY_LATER_STYLE + '</style></head><body><main>'
            '<h1>' + title + '</h1><p>' + body + '</p>'
            '<a class="button" href="' + RESTART_LOGIN_PATH + '">' + action + '</a>'
            '</main></body></html>')


def _retry_later_response(request, headers):
    return HTMLResponse(_retry_later_page(request), status_code=503, headers=headers)


# Authority rejection codes that mean the presented credential is dead. When
# a refresh carries one of these, the shared cookie is cleared and the client
# falls back to a plain guest; anything else is this host's failure and stays
# 503 so the browser keeps its retry semantics.
_REFRESH_REJECTION_CODES = frozenset({
    'invalid_grant', 'invalid_token', 'invalid_client', 'unauthorized_client',
    'invalid_exchange', 'unknown_account', 'invalid_shared_credential',
    'invalid_verified_claims', 'invalid_token_endpoint', 'exchange_rejected',
})


def _refresh_failure_code(error):
    """The authority's closed rejection code for this refresh, or None.

    Follows explicit causes like ``_finish_failure_code``; only allow-listed
    literal codes ever surface, so no token or body text can leak into the
    log line or drive the 401 decision.
    """
    seen = set()
    while isinstance(error, Exception) and id(error) not in seen:
        seen.add(id(error))
        candidate = getattr(error, 'code', None)
        if not isinstance(candidate, str) and len(error.args) == 1:
            candidate = error.args[0]
        if isinstance(candidate, str) and candidate in _REFRESH_REJECTION_CODES:
            return candidate
        error = error.__cause__
    return None


def _finish_failure_code(error, stage):
    from .history import HistoryConflict
    code = stage + '_failed'
    seen = set()
    while isinstance(error, Exception) and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, HistoryConflict):
            code = 'shared_profile_identity_conflict'
        candidate = getattr(error, 'code', None)
        if not isinstance(candidate, str) and len(error.args) == 1:
            candidate = error.args[0]
        if isinstance(candidate, str) and candidate in _FINISH_FAILURE_CODES:
            code = candidate
        error = error.__cause__
    return code


def issue_shared_cookies(response, access, refresh):
    """Service host only; refresh is sent only to the common-auth endpoints."""
    response.set_cookie(ACCESS_COOKIE, access, secure=True, httponly=True,
                        samesite='lax', path='/', max_age=ACCESS_SECONDS)
    response.set_cookie(REFRESH_COOKIE, refresh, secure=True, httponly=True,
                        samesite='lax', path=REFRESH_PATH, max_age=REFRESH_SECONDS)
    # Presentation-only hint: never carries a credential or authorizes access.
    response.set_cookie(MARKER_COOKIE, '1', secure=True, httponly=True,
                        samesite='lax', path='/', max_age=REFRESH_SECONDS)
    return response


def clear_shared_cookies(response):
    response.delete_cookie(ACCESS_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, secure=True, httponly=True, samesite='lax')
    response.delete_cookie(MARKER_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response


def clear_all_local_cookies(response):
    """Logout-side local clearing across both credential families.

    A local sign-out is owned by the browser even when a remote revocation
    cannot be confirmed (design §7 (5)): cookies go, the response still
    reports what happened.
    """
    clear_shared_cookies(response)
    response.delete_cookie(STATE_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    response.delete_cookie(LOGIN_RETURN_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    response.delete_cookie(SESSION_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response


async def attach_chat_default_session(
    response, request, *, user_id, access, verifier,
):
    """Issue the Chat default session for a verified common login (#7364).

    The common login callback used to issue only the shared access/refresh
    cookies. A shared-login-only account therefore had no Chat session cookie
    and no identity shadow row, so the first shadow consumer (connectors,
    calendar, PC device directory) failed closed as soon as the account's last
    legacy session expired — even though this login was still verified.

    The verified access claims are re-read here (JWKS is cached), the canonical
    subject is bound to one B62 session, its shadow pointer is written, and the
    signed Chat session cookie is set on the response. The canonical session is
    the one the logout paths revoke (#5225/#7334). Any failure leaves the
    response untouched: the shared login still succeeds with its own cookies
    (the pre-existing cookie-only compatibility mode).
    """

    try:
        claims = verifier.verify(access)
        if inspect.isawaitable(claims):
            claims = await claims
        account_id = claims.get("accountId") if isinstance(claims, dict) else None
        if not isinstance(account_id, str) or not account_id.startswith("sub_"):
            return None
        settings = getattr(getattr(request, "app", None), "state", None)
        settings = getattr(settings, "settings", None)
        if settings is None or not getattr(settings, "session_secret", None):
            return None
        from .auth import SESSION_COOKIE, create_session_token, session_cookie_kwargs
        from .auth_routes import _write_shared_identity_shadow_after_login

        authenticated_at = datetime.now(timezone.utc)
        expires_at = authenticated_at + timedelta(seconds=settings.session_max_age_seconds)
        canonical_session_id = await _write_shared_identity_shadow_after_login(
            request,
            product_user_id=user_id,
            canonical_subject_id=account_id,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
        )
        token = create_session_token(
            settings,
            user_id,
            now=int(authenticated_at.timestamp()),
            canonical_session_id=canonical_session_id,
        )
        response.set_cookie(SESSION_COOKIE, token, **session_cookie_kwargs(settings))
        return canonical_session_id
    except Exception:
        return None


def chat_session_reattach_needed(request) -> bool:
    """Whether the browser no longer holds a working Chat default session.

    The common login outlives the Chat default session: the shared refresh
    credential lives 30 days while the Chat session cookie lives 7. The refresh
    must re-establish the Chat session when the browser holds none — it expired,
    was cleared, or its canonical session was revoked behind this request's
    back (the request-time guard's own verdict) — so devices·connectors keep
    resolving for the common login's whole life (#7381). A still-working Chat
    session is left alone: the refresh never mints a second canonical session
    for it.
    """

    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return True
    settings = getattr(getattr(request, "app", None), "state", None)
    settings = getattr(settings, "settings", None)
    if settings is None:
        # Without the app composition there is nothing to re-establish against.
        return False
    if decode_session_claims(settings, raw) is None:
        # Expired or unparsable: the browser holds no working Chat session.
        return True
    verdict = session_verdict(request)
    if verdict is not None and not verdict.authenticated:
        # The request-time guard resolved this very request and refused the
        # cookie's canonical session, so the cookie authenticates nothing.
        return True
    return False


def safe_login_return(value):
    """Only a same-origin absolute path may become the post-login Location."""
    if not isinstance(value, str):
        return '/'
    value = value.strip()
    if (not value or len(value) > LOGIN_RETURN_MAX_CHARS
            or not value.startswith('/') or value.startswith('//')
            or '\\' in value or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return '/'
    return value


def set_login_return_cookie(response, target):
    response.set_cookie(LOGIN_RETURN_COOKIE, safe_login_return(target),
                        secure=True, httponly=True, samesite='lax', path='/', max_age=600)
    return response


def login_return_target(request):
    return safe_login_return(request.cookies.get(LOGIN_RETURN_COOKIE))


def clear_login_return_cookie(response):
    response.delete_cookie(LOGIN_RETURN_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response


class SharedLoginFlow(ComparisonFlow):
    """Use the existing assertion/WebCrypto contract; keep tokens server-side.

    ``issue_session`` must persist the verified access and refresh credentials
    safely and return a response; this skeleton does not install a cookie or
    convert a shared access token to an unbounded legacy session.
    """

    def __init__(self, *, issue_session, resolve_account, revoke_session=None, provision_profile=None, public_base_url=None, extra_origins=(), **kwargs):
        base = (public_base_url or 'https://chat.padiem.net').rstrip('/')
        url = urlsplit(base)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError('invalid_shared_login_origin')
        self.public_base_url = base
        # #6850: the canonical host stays first; the reviewed parallel hosts
        # (the pages.dev entry) are the only additions. Cookies are host-scoped,
        # so each host runs its own login round trip against the one authority.
        self.allowed_origins = tuple(dict.fromkeys(
            [base] + [value for value in extra_origins if isinstance(value, str) and value and value != base]
        ))
        self.callback = base + '/auth/shared/callback'
        super().__init__(**kwargs)
        if not callable(issue_session) or not callable(resolve_account):
            raise ValueError('invalid_session_integration')
        self.issue_session = issue_session
        self.resolve_account = resolve_account
        self.revoke_session = revoke_session
        self.provision_profile = provision_profile

    def callback_for(self, request) -> str:
        """The callback this request's own reviewed host must use.

        ``chat.padiem.net`` keeps ``public_base_url``. A second reviewed host
        gets its own ``/auth/shared/callback`` so the state cookie, the OAuth
        round trip and the redirect all stay on the host the browser opened.
        A host outside the reviewed list never changes the callback.
        """
        if len(self.allowed_origins) == 1:
            return self.callback
        raw = request.headers.get('x-forwarded-host') or request.headers.get('host') or ''
        host = str(raw).split(',')[0].strip().lower()
        if not host:
            return self.callback
        origin = 'https://' + host
        if origin not in self.allowed_origins:
            return self.callback
        return origin + '/auth/shared/callback'

    def origin_allowed(self, request) -> bool:
        """True when this mutation came from a reviewed host of this app."""
        origin = request.headers.get('origin')
        return isinstance(origin, str) and origin.strip() in self.allowed_origins

    async def start_login(self, request, *, provider: str | None = None):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        data = _encoded({'state': state, 'verifier': verifier, 'exp': int(self.clock()) + 600})
        cookie = data + '.' + _b64(self._mac(b'shared-login', data.encode('ascii')))
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.callback_for(request),
            'state': state,
            'code_challenge': _b64(hashlib.sha256(verifier.encode('ascii')).digest()),
            'code_challenge_method': 'S256',
        }
        requested_provider = provider
        if requested_provider is None:
            query_params = getattr(request, 'query_params', None)
            if query_params is not None and hasattr(query_params, 'get'):
                requested_provider = query_params.get('provider')
        if requested_provider == 'google':
            params['provider'] = 'google'
        query = urlencode(params)
        response = RedirectResponse(AUTH + '/login?' + query, status_code=302,
                                    headers={'cache-control': 'no-store', 'referrer-policy': 'no-referrer'})
        response.set_cookie(STATE_COOKIE, cookie, secure=True, httponly=True, samesite='lax', path='/', max_age=600)
        return response

    async def finish_login(self, request):
        from .request_telemetry import current_request_id, is_safe_request_id
        from .shared_login_timing import begin_login_timings, end_login_timings

        request_id = current_request_id()
        if not is_safe_request_id(request_id):
            request_id = 'none'
        token, timing_details = begin_login_timings()
        try:
            return await self._finish_login_timed(request, request_id, timing_details)
        finally:
            end_login_timings(token)

    async def _finish_login_timed(self, request, request_id, timing_details):
        headers = {'cache-control': 'no-store', 'referrer-policy': 'no-referrer'}
        stage = 'validate_flow'
        # A callback can hold three outbound calls before a session exists. Which
        # stage is slow decides whether this is a host problem or an authority
        # problem, so each one is measured; only names and milliseconds are logged.
        started = last_mark = time.monotonic()
        marks = []

        def mark(name):
            nonlocal last_mark
            now = time.monotonic()
            marks.append(f'{name}_ms={int((now - last_mark) * 1000)}')
            last_mark = now

        try:
            states, codes = request.query_params.getlist('state'), request.query_params.getlist('code')
            if len(states) != 1 or len(codes) != 1 or not codes[0]:
                raise ValueError('invalid_flow')
            raw_cookie = request.cookies.get(STATE_COOKIE, '')
            if not raw_cookie:
                # #6922: the browser carries no state for this host — the login
                # was started on another host, more than 10 minutes ago, or
                # with cookies blocked. The journal names that apart from a
                # forged cookie and from an expired or foreign state below.
                raise ValueError('state_cookie_missing')
            parts = raw_cookie.split('.')
            if len(parts) != 2:
                raise ValueError('invalid_cookie')
            mac = _b64(self._mac(b'shared-login', parts[0].encode('ascii')))
            if not hmac.compare_digest(mac, parts[1]):
                raise ValueError('invalid_cookie')
            state = json.loads(_un64(parts[0]))
            if (type(state.get('exp')) is not int
                    or not isinstance(state.get('state'), str)
                    or not isinstance(state.get('verifier'), str)):
                raise ValueError('invalid_state')
            if state['exp'] <= int(self.clock()):
                raise ValueError('state_expired')
            if not hmac.compare_digest(state['state'], states[0]):
                raise ValueError('state_mismatch')
            mark('validate_flow')
            stage = 'client_assertion'
            assertion = await self._assertion(int(self.clock()))
            mark('client_assertion')
            stage = 'exchange'
            tokens = await _await(self.exchange(TOKEN_URL, {
                'client_id': self.client_id,
                'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                'client_assertion': assertion,
                'grant_type': 'authorization_code', 'code': codes[0],
                'redirect_uri': self.callback_for(request), 'code_verifier': state['verifier'],
            }))
            if not isinstance(tokens, dict):
                raise ValueError('invalid_exchange')
            access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ValueError('invalid_exchange')
            mark('exchange')
            stage = 'resolve_account'
            user = await _await(self.resolve_account(request, access))
            if not isinstance(user, str) or not user:
                raise ValueError('unknown_account')
            mark('resolve_account')
            if self.provision_profile is not None:
                stage = 'provision_profile'
                await _await(self.provision_profile(request, user, access, tokens))
                mark('provision_profile')
            stage = 'issue_session'
            response = await _await(self.issue_session(request, user, access, refresh))
            if not isinstance(response, RedirectResponse):
                raise ValueError('invalid_session_response')
            response.headers.update(headers)
            mark('issue_session')
            # #7078 B: register the newly issued padiem-auth session in the
            # shared cache so local verification maps the subject and permits a
            # post-password-change fresh login without upstream calls.
            try:
                from .auth_validation_cache import _state_for_request, cache_for_request
                from .config import session_local_verify_enabled
                state_obj = _state_for_request(request)
                if session_local_verify_enabled(getattr(state_obj, 'settings', None)):
                    cache = cache_for_request(request)
                    verifier = getattr(getattr(self, 'auth', None), 'verifier', None)
                    if cache is not None and callable(getattr(cache, 'record_allowed_session', None)) and callable(getattr(verifier, 'verify', None)):
                        claims = await _await(verifier.verify(access))
                        if isinstance(claims, dict):
                            exp = claims.get('expiresAt')
                            await cache.record_allowed_session(
                                session_id=claims.get('sessionId') or '',
                                user_id=user,
                                account_id=claims.get('accountId'),
                                valid_until=(float(exp) + 60.0) if isinstance(exp, (int, float)) else None,
                            )
            except Exception:
                pass
            # #7078: a previous password change/reset may have failed to revoke
            # the shared sessions; this successful login is a safe retry point.
            try:
                from .shared_session_revoke import flush_pending
                await flush_pending(request, user)
            except Exception:
                pass
            # Same retry point for a failed external AI credential revocation.
            try:
                from .external_token_revoke import flush_pending as flush_external_tokens
                await flush_external_tokens(request, user)
            except Exception:
                pass
            # This module's logger has no handler in the host, so INFO never
            # reaches the journal and a successful login left no stage record.
            # The line is the one ops reads, in the failed line's own shape.
            from .shared_login_timing import format_login_timing_fields
            detail_fields = marks + format_login_timing_fields(timing_details)
            print('shared_login_timing outcome=ok total_ms=%d request_id=%s%s' % (
                int((time.monotonic() - started) * 1000), request_id,
                ' ' + ' '.join(detail_fields) if detail_fields else ''), flush=True)
        except Exception as exc:
            code = _finish_failure_code(exc, stage)
            logger.warning('shared_login_finish_failed stage=%s code=%s', stage, code)
            from .shared_login_timing import format_login_timing_fields
            detail_fields = marks + format_login_timing_fields(timing_details)
            logger.warning('shared_login_timing outcome=failed stage=%s total_ms=%d request_id=%s%s',
                           stage, int((time.monotonic() - started) * 1000), request_id,
                           ' ' + ' '.join(detail_fields) if detail_fields else '')
            if ((stage == 'validate_flow' and code in _FLOW_RESTART_CODES)
                    or (stage == 'exchange' and code in _EXCHANGE_RESTART_CODES)):
                response = _restart_login_response(code, headers)
            else:
                # #7699: a browser is on this URL. Answer with the retry page,
                # not raw JSON; the 503 itself stays retryable.
                response = _retry_later_response(request, headers)
        response.delete_cookie(STATE_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
        return response

    async def refresh(self, request):
        """The authority owns rotation and the 30-second concurrent-use grace."""
        headers = {'cache-control': 'no-store', 'referrer-policy': 'no-referrer'}
        stage = 'refresh_exchange'
        try:
            if not self.origin_allowed(request):
                return JSONResponse({'error': 'invalid_origin'}, status_code=403, headers=headers)
            old = request.cookies.get(REFRESH_COOKIE)
            if not old:
                return JSONResponse({'error': 'not_authenticated'}, status_code=401, headers=headers)
            tokens = await _await(self.exchange(TOKEN_URL, {
                'client_id': self.client_id,
                'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                'client_assertion': await self._assertion(int(self.clock())),
                'grant_type': 'refresh_token', 'refresh_token': old,
            }))
            access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ValueError('invalid_exchange')
            stage = 'refresh_account'
            user = await _await(self.resolve_account(request, access))
            if not isinstance(user, str) or not user:
                raise ValueError('unknown_account')
            # #7078: keep retrying a pending credential-change revocation.
            from .auth_validation_cache import _state_for_request
            from .config import session_local_verify_enabled
            state_obj = _state_for_request(request)
            local_mode = session_local_verify_enabled(getattr(state_obj, 'settings', None))
            had_pending = False
            flushed_pending = True
            try:
                from .shared_session_revoke import flush_pending, has_pending
                if local_mode:
                    had_pending = await has_pending(request, user)
                flushed_pending = await flush_pending(request, user)
            except Exception:
                flushed_pending = False
            if local_mode and had_pending:
                try:
                    from .auth_validation_cache import record_auth_revocation
                    await record_auth_revocation(request, user_ids=(user,))
                except Exception:
                    pass
                if flushed_pending:
                    response = JSONResponse({'error': 'authentication_expired'}, status_code=401, headers=headers)
                    return clear_shared_cookies(response)
                return JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)
            # Same retry point for a failed external AI credential revocation.
            try:
                from .external_token_revoke import flush_pending as flush_external_tokens
                await flush_external_tokens(request, user)
            except Exception:
                pass
            stage = 'refresh_issue'
            response = issue_shared_cookies(JSONResponse({'ok': True}, headers=headers), access, refresh)
            if local_mode:
                try:
                    from .auth_validation_cache import cache_for_request
                    cache = cache_for_request(request)
                    verifier = getattr(getattr(self, 'auth', None), 'verifier', None)
                    if cache is not None and callable(getattr(cache, 'record_allowed_session', None)) and callable(getattr(verifier, 'verify', None)):
                        claims = await _await(verifier.verify(access))
                        if isinstance(claims, dict):
                            exp = claims.get('expiresAt')
                            await cache.record_allowed_session(
                                session_id=claims.get('sessionId') or '',
                                user_id=user,
                                account_id=claims.get('accountId'),
                                valid_until=(float(exp) + 60.0) if isinstance(exp, (int, float)) else None,
                            )
                except Exception:
                    pass
            # #7381: the renewed common login re-attaches the Chat default
            # session when the browser no longer holds a working one, so a
            # 30-day common login keeps devices·connectors healthy past the
            # 7-day Chat session. Best-effort exactly like the callback's
            # attachment: any failure leaves the refreshed cookies untouched.
            if chat_session_reattach_needed(request):
                verifier = getattr(getattr(self, 'auth', None), 'verifier', None)
                if callable(getattr(verifier, 'verify', None)):
                    await attach_chat_default_session(
                        response, request, user_id=user, access=access, verifier=verifier,
                    )
            return response
        except Exception as exc:
            # #6679: a stale shared-session cookie must not wedge the browser.
            # When the authority itself rejects the refresh token (invalid_grant
            # and other closed authority rejections), the cookie is dead: clear
            # it so the next status read reports a plain guest and the login
            # entry opens. Only failures that are NOT an authority rejection
            # (this host cannot reach the authority, etc.) stay 503 so the
            # client keeps its retry semantics. The logged line is closed:
            # stage and code only, never a token or body.
            code = _refresh_failure_code(exc)
            detail = code or ('exchange_unavailable' if stage == 'refresh_exchange' else 'unavailable')
            print('shared_refresh_result outcome=%s stage=%s code=%s' % (
                'rejected' if code is not None else 'unavailable',
                stage, detail), flush=True)
            if code is not None:
                response = JSONResponse({'error': 'authentication_expired'}, status_code=401, headers=headers)
                return clear_shared_cookies(response)
            return JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)

    async def logout(self, request):
        headers = {'cache-control': 'no-store'}
        if request.headers.get('origin') != self.public_base_url:
            return JSONResponse({'error': 'invalid_origin'}, status_code=403, headers=headers)
        # End the legacy canonical session this browser also holds. A failure
        # never blocks the local sign-out below (design §7 (5)), and it is no
        # longer answered as success either (#7554): the cookies still go, the
        # answer is a retryable refusal.
        from .logout_revocation import (
            hold_unrevoked_session_locally,
            journal_logout_revocation_failure,
            logout_revocation_failed_response,
            revocation_outcome_failed,
        )
        legacy_failed = False
        try:
            from .auth_routes import _revoke_canonical_session
            legacy_code = await _revoke_canonical_session(request)
            if revocation_outcome_failed(request, legacy_code):
                legacy_failed = True
                journal_logout_revocation_failure('shared_legacy', legacy_code)
        except Exception as exc:
            print('shared_logout_result outcome=legacy_revoke_failed stage=logout code=%s' % (
                _finish_failure_code(exc, 'logout'),), flush=True)
            # Only a request that carries a legacy session, on a deployment
            # with a canonical authority, has one to end.
            state = getattr(request.scope.get('app'), 'state', None)
            if (request.cookies.get(SESSION_COOKIE)
                    and getattr(state, 'control_plane_identity_authority', None) is not None):
                legacy_failed = True
                journal_logout_revocation_failure('shared_legacy', 'exception')
        from .auth_validation_cache import _state_for_request
        from .config import session_local_verify_enabled
        state_obj = _state_for_request(request)
        settings_obj = getattr(state_obj, 'settings', None)
        local_mode = session_local_verify_enabled(settings_obj)

        old = request.cookies.get(REFRESH_COOKIE)
        remote_revoked = False
        remote_failed = False
        if old:
            try:
                if not callable(self.revoke_session):
                    raise ValueError('revoke_unavailable')
                await _await(self.revoke_session({
                    'client_id': self.client_id,
                    'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                    'client_assertion': await self._assertion(int(self.clock())),
                    'refresh_token': old,
                }))
                remote_revoked = True
            except Exception as exc:
                # #6679: a failed revoke still owns the local sign-out — the
                # cookies are cleared on this device. #7554: the answer is no
                # longer ok, because the remote session is still alive. The
                # logged line is closed.
                print('shared_logout_result outcome=revoke_failed stage=logout code=%s' % (
                    _finish_failure_code(exc, 'logout'),), flush=True)
                journal_logout_revocation_failure('shared_remote', _finish_failure_code(exc, 'logout') or 'failed')
                remote_failed = True
                if not local_mode:
                    return clear_all_local_cookies(logout_revocation_failed_response(headers=headers))
        if local_mode:
            from .auth_validation_cache import record_auth_revocation
            from .session_revocation_guard import verify_access_cookie_for_revocation

            verified_access = await verify_access_cookie_for_revocation(request)
            legacy_claims = (
                decode_session_claims(settings_obj, request.cookies.get(SESSION_COOKIE))
                if settings_obj is not None else None
            )
            refresh_sid = None
            if remote_revoked and isinstance(old, str):
                parts = old.split('.')
                if len(parts) == 3 and parts[1]:
                    refresh_sid = parts[1]
            sids = tuple(
                s for s in (
                    verified_access.get('sessionId') if verified_access else None,
                    refresh_sid,
                    legacy_claims.canonical_session_id if legacy_claims else None,
                ) if isinstance(s, str) and s
            )
            if sids:
                try:
                    await record_auth_revocation(request, session_ids=sids)
                except Exception:
                    return clear_all_local_cookies(
                        JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)
                    )
            if legacy_failed and legacy_claims is not None:
                await hold_unrevoked_session_locally(request, legacy_claims.canonical_session_id)
            if remote_failed:
                return clear_all_local_cookies(logout_revocation_failed_response(headers=headers))
        auth = getattr(self, 'auth', None)
        try:
            invalidate = getattr(auth, 'invalidate_session', None)
            if callable(invalidate):
                await _await(invalidate(request, request.cookies.get(ACCESS_COOKIE)))
            else:
                # Older injected auth ports have only user_id(). There is
                # no cache to invalidate on their default composition;
                # if one is configured, safely discard it in full.
                from .auth_validation_cache import cache_for_request
                cache = cache_for_request(request)
                if cache is not None:
                    await cache.invalidate_all()
        except Exception:
            return JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)
        if legacy_failed:
            return clear_all_local_cookies(logout_revocation_failed_response(headers=headers))
        return clear_all_local_cookies(JSONResponse({'ok': True}, headers=headers))

    def login_routes(self):
        return [Route('/auth/shared/start', self.start_login, methods=['GET']),
                Route('/auth/shared/callback', self.finish_login, methods=['GET']),
                Route('/auth/shared/refresh', self.refresh, methods=['POST']),
                Route('/auth/shared/logout', self.logout, methods=['POST'])]


async def revoke_with_httpx(data):
    from . import httpx_compat as httpx
    async with httpx.AsyncClient(follow_redirects=False) as client:
        from .shared_auth_compare_flow import SERVER_HEADERS
        async with client.stream('POST', AUTH + '/logout', data=data, headers=SERVER_HEADERS) as response:
            if response.status_code != 200:
                print(f"[shared_login] revoke status={response.status_code}", flush=True)
                raise ValueError('revoke_failed')


async def create_worker_shared_login_flow(env, authority):
    """No secrets or routes are loaded while the explicit switch is off."""
    from .worker_config import binding_value, resolve_secret_binding
    if str(binding_value(env, 'PADIEM_CHAT_SHARED_LOGIN_ENABLED') or '').strip().lower() != 'true':
        return None
    from .auth_routes import current_user_id
    from .shared_auth_adapter import SharedChatAuth
    from .shared_auth_compare_flow import WorkerJwksVerifier, exchange_with_httpx
    try:
        if authority is None:
            print('shared_login: missing IDENTITY_AUTHORITY_SERVICE')
            return None
        private = await resolve_secret_binding(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK')
        state = await resolve_secret_binding(env, 'PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY')
        kid = binding_value(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_KID')
        missing = [name for name, value in (
            ('PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK', private),
            ('PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY', state),
            ('PADIEM_CHAT_SHARED_AUTH_CLIENT_KID', kid),
        ) if not value]
        if missing:
            print('shared_login: missing ' + ', '.join(missing))
            return None
        client_id = str(binding_value(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_ID') or 'b62').strip()
        public_base_url = binding_value(env, 'PADIEM_CHAT_PUBLIC_BASE_URL')
        verifier = WorkerJwksVerifier(audience=client_id)
        auth = SharedChatAuth(verifier=verifier, authority=authority, legacy=current_user_id)

        async def provision(request, user, access, tokens):
            from .b66_signup_notifications import deliver_after_signup
            from .shared_profile_provision import provision_shared_profile
            store = getattr(request.app.state, 'history_store', None)
            if store is None or not callable(getattr(store, 'upsert_shared_user', None)):
                raise ValueError('profile_store_unavailable')
            await provision_shared_profile(request, user, access, tokens, verifier=verifier,
                store=store, legacy_user=current_user_id, notify=deliver_after_signup)

        async def issue(request, user, access, refresh):
            response = RedirectResponse(login_return_target(request), status_code=302)
            await attach_chat_default_session(
                response, request, user_id=user, access=access, verifier=verifier,
            )
            issue_shared_cookies(response, access, refresh)
            return clear_login_return_cookie(response)

        flow = SharedLoginFlow(state_key=_un64(state), client_id=client_id, public_base_url=public_base_url,
            extra_origins=parse_extra_origins(binding_value(env, 'PADIEM_CHAT_PUBLIC_BASE_URLS')), client_jwk=json.loads(private),
            kid=str(kid), operator_guard=lambda request: False, legacy_user=current_user_id,
            comparator=lambda *args: None, exchange=exchange_with_httpx, resolve_account=auth.user_id,
            issue_session=issue, revoke_session=revoke_with_httpx, provision_profile=provision)
        flow.auth = auth
        return flow
    except Exception:
        print('shared_login: unavailable')
        return None
