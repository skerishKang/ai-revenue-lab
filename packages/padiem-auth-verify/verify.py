"""Verify PADIEM ES256 access tokens with the fixed issuer and JWKS URL."""
import base64
import json
import re
import threading
import time
import urllib.request
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

ISSUER = 'https://auth.padiem.net'
JWKS_URL = ISSUER + '/.well-known/jwks.json'

# #7078 B: a last-good key set stays usable for at most one hour after the last
# successful fetch. A JWKS outage must not log live users out, while a rotated
# or compromised key still stops being honoured within a bounded window.
STALE_KEY_MAX_SECONDS = 3600
# One unknown-kid refresh per burst: concurrent requests carrying the same new
# kid share the first fetch instead of hammering the key endpoint.
KID_REFRESH_MIN_INTERVAL_SECONDS = 5


def _decode(s):
    if not isinstance(s, str) or not s or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in s):
        raise ValueError('invalid_encoding')
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def _fetch():
    # Refuse redirects: the trusted key URL is fixed, not token-controlled.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    request = urllib.request.Request(JWKS_URL, headers={"User-Agent": "padiem-boot-recovery/1.0"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
        return json.load(response)


def require_claims(verifier, body, now):
    """Reject a token whose claims do not belong to this product and time.

    #7821: the two time conditions are named separately, as #7699 already does
    for the comparison flow (``token_not_yet_valid`` / ``token_expired``). A
    host clock that trails the issuer by a moment used to look exactly like a
    forged claim in the log; the refusal itself is unchanged and every other
    condition still raises ``invalid_claims``.
    """
    if body.get('iss') != ISSUER or body.get('aud') != verifier.audience or body.get('token_use') != 'access':
        raise ValueError('invalid_claims')
    if type(body.get('iat')) is not int:
        raise ValueError('invalid_claims')
    if body['iat'] > now + verifier.leeway_seconds:
        raise ValueError('token_not_yet_valid')
    if type(body.get('exp')) is not int:
        raise ValueError('invalid_claims')
    if body['exp'] + verifier.leeway_seconds <= now:
        raise ValueError('token_expired')
    if body['exp'] > body['iat'] + 900:
        raise ValueError('invalid_claims')
    account_id = body.get('account_id')
    if (not isinstance(body.get('sub'), str) or not body['sub']
            or not isinstance(account_id, str) or not re.fullmatch(r'sub_[A-Za-z0-9_-]+', account_id)
            or not isinstance(body.get('sid'), str) or not body['sid']):
        raise ValueError('invalid_claims')
    if 'account_created_at' in body and (type(body['account_created_at']) is not int or body['account_created_at'] < 0 or body['account_created_at'] > body['iat']):
        raise ValueError('invalid_claims')
    if 'amr' in body and (not isinstance(body['amr'], list) or not body['amr'] or not all(isinstance(x, str) and x for x in body['amr'])):
        raise ValueError('invalid_claims')


class Verifier:
    def __init__(self, audience, fetcher=_fetch, clock=time.time, cache_seconds=300,
                 leeway_seconds=0, stale_seconds=STALE_KEY_MAX_SECONDS):
        if (not isinstance(audience, str) or not audience or cache_seconds <= 0 or
                type(leeway_seconds) is not int or not 0 <= leeway_seconds <= 60 or
                type(stale_seconds) is not int or stale_seconds <= 0):
            raise ValueError('invalid_configuration')
        self.audience, self.fetcher, self.clock, self.cache_seconds = audience, fetcher, clock, cache_seconds
        self.leeway_seconds = leeway_seconds
        self.stale_seconds = stale_seconds
        self.cached, self.until = None, 0
        self.stale_until = 0
        # Last outcome of _keys, for the request layer's reason-code log:
        # jwks_refreshed / jwks_stale_used / jwks_unavailable.
        self.last_refresh_reason = ''
        self._last_fetch = 0.0
        self._last_force = 0.0
        self._lock = threading.Lock()

    def _fetch_keys(self):
        data = self.fetcher()
        if not isinstance(data, dict) or not isinstance(data.get('keys'), list):
            raise ValueError('invalid_jwks')
        now = self.clock()
        self.cached = data['keys']
        self.until = now + self.cache_seconds
        self.stale_until = now + max(self.cache_seconds, self.stale_seconds)
        self._last_fetch = now
        self.last_refresh_reason = 'jwks_refreshed'
        return self.cached

    def _keys(self, force=False):
        """Return the JWKS key list, fetching at most once for concurrent callers.

        A cold or expired cache is refreshed on this call (bounded by the
        fetcher timeout) instead of refusing the request. If that refresh
        fails, the last good keys are reused until STALE_KEY_MAX_SECONDS after
        the last successful fetch; only then does the error propagate (the
        request layer turns it into a fail-closed 503).
        """
        with self._lock:
            now = self.clock()
            if not force and self.cached is not None and now < self.until:
                return self.cached
            if force and self.cached is not None and self._last_force and now - self._last_force < KID_REFRESH_MIN_INTERVAL_SECONDS:
                return self.cached
            try:
                keys = self._fetch_keys()
                if force:
                    self._last_force = now
                return keys
            except Exception:
                if self.cached is not None and now < self.stale_until:
                    self.last_refresh_reason = 'jwks_stale_used'
                    return self.cached
                self.last_refresh_reason = 'jwks_unavailable'
                raise

    def verify(self, token):
        parts = token.split('.') if isinstance(token, str) else []
        if len(parts) != 3:
            raise ValueError('invalid_token')
        header, body = json.loads(_decode(parts[0])), json.loads(_decode(parts[1]))
        if header.get('alg') != 'ES256' or header.get('typ') != 'JWT' or not isinstance(header.get('kid'), str) or not header['kid'] or any(k in header for k in ('crit', 'jku', 'jwk', 'x5u')):
            raise ValueError('invalid_header')
        def match(keys):
            return [k for k in keys if k.get('kid') == header['kid'] and k.get('kty') == 'EC' and k.get('crv') == 'P-256' and not k.get('d') and k.get('alg', 'ES256') == 'ES256' and k.get('use', 'sig') == 'sig']
        matches = match(self._keys())
        if not matches:
            # Key rotation: one bounded refresh, then the token is just invalid.
            matches = match(self._keys(True))
        if len(matches) != 1:
            raise ValueError('unknown_key')
        jwk = matches[0]
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(_decode(jwk['x']), 'big'), int.from_bytes(_decode(jwk['y']), 'big'), ec.SECP256R1()).public_key()
        signature = _decode(parts[2])
        if len(signature) != 64:
            raise ValueError('invalid_signature')
        try:
            key.verify(encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big')), (parts[0] + '.' + parts[1]).encode(), ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            # Same refusal, reported with this module's own code instead of
            # letting the crypto library's exception type leak to the caller.
            raise ValueError('invalid_signature') from None
        now = int(self.clock())
        require_claims(self, body, now)
        result = dict(subject=body['sub'], accountId=body['account_id'], sessionId=body['sid'], expiresAt=body['exp'])
        if 'account_created_at' in body:
            result['accountCreatedAt'] = body['account_created_at']
        if 'amr' in body:
            result['amr'] = list(body['amr'])
        return result
