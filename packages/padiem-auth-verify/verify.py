"""Verify PADIEM ES256 access tokens with the fixed issuer and JWKS URL."""
import base64
import json
import time
import urllib.request
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

ISSUER = 'https://auth.padiem.net'
JWKS_URL = ISSUER + '/.well-known/jwks.json'


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


class Verifier:
    def __init__(self, audience, fetcher=_fetch, clock=time.time, cache_seconds=300):
        if not isinstance(audience, str) or not audience or cache_seconds <= 0:
            raise ValueError('invalid_configuration')
        self.audience, self.fetcher, self.clock, self.cache_seconds = audience, fetcher, clock, cache_seconds
        self.cached, self.until = None, 0

    def _keys(self, force=False):
        if not force and self.cached is not None and self.clock() < self.until:
            return self.cached
        data = self.fetcher()
        if not isinstance(data, dict) or not isinstance(data.get('keys'), list):
            raise ValueError('invalid_jwks')
        self.cached, self.until = data['keys'], self.clock() + self.cache_seconds
        return self.cached

    def verify(self, token):
        import re
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
            matches = match(self._keys(True))
        if len(matches) != 1:
            raise ValueError('unknown_key')
        jwk = matches[0]
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(_decode(jwk['x']), 'big'), int.from_bytes(_decode(jwk['y']), 'big'), ec.SECP256R1()).public_key()
        signature = _decode(parts[2])
        if len(signature) != 64:
            raise ValueError('invalid_signature')
        key.verify(encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big')), (parts[0] + '.' + parts[1]).encode(), ec.ECDSA(hashes.SHA256()))
        now = int(self.clock())
        if (body.get('iss') != ISSUER or body.get('aud') != self.audience or body.get('token_use') != 'access' or
            type(body.get('iat')) is not int or body['iat'] > now or type(body.get('exp')) is not int or body['exp'] <= now or body['exp'] > body['iat'] + 900 or
            not isinstance(body.get('sub'), str) or not body['sub'] or not isinstance(body.get('account_id'), str) or not re.fullmatch(r'sub_[A-Za-z0-9_-]+', body['account_id']) or not isinstance(body.get('sid'), str) or not body['sid']):
            raise ValueError('invalid_claims')
        return dict(subject=body['sub'], accountId=body['account_id'], sessionId=body['sid'], expiresAt=body['exp'])
