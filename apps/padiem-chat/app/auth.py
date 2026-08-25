from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SESSION_COOKIE = "padiem_session"
OAUTH_STATE_COOKIE = "padiem_oauth_state"
OAUTH_STATE_MAX_AGE_SECONDS = 600
MAX_AUTH_RESPONSE_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True)
class AuthError(Exception):
    status_code: int
    code: str
    user_message: str

    def __str__(self) -> str:
        return self.user_message


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _signed_token(secret: str, purpose: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64url_encode(raw)
    key = hmac.new(secret.encode("utf-8"), purpose.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(key, body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(sig)}"


def _verify_token(secret: str, purpose: str, token: str, now: int | None = None) -> dict[str, Any] | None:
    try:
        body, sig_text = token.split(".", 1)
        key = hmac.new(secret.encode("utf-8"), purpose.encode("utf-8"), hashlib.sha256).digest()
        expected = hmac.new(key, body.encode("ascii"), hashlib.sha256).digest()
        supplied = _b64url_decode(sig_text)
        if not hmac.compare_digest(expected, supplied):
            return None
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        exp = payload.get("exp")
        if not isinstance(exp, int) or exp < (int(time.time()) if now is None else now):
            return None
        return payload
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, base64.binascii.Error):
        return None


def create_session_token(settings: Settings, user_id: str, now: int | None = None) -> str:
    if not settings.session_secret:
        raise AuthError(503, "auth_unavailable", "로그인을 현재 사용할 수 없습니다.")
    issued = int(time.time()) if now is None else now
    return _signed_token(
        settings.session_secret,
        "padiem-chat/session/v1",
        {"v": 1, "uid": user_id, "exp": issued + settings.session_max_age_seconds},
    )


def decode_session_token(settings: Settings, token: str | None, now: int | None = None) -> str | None:
    if not token or not settings.session_secret:
        return None
    payload = _verify_token(settings.session_secret, "padiem-chat/session/v1", token, now=now)
    if not payload or payload.get("v") != 1:
        return None
    uid = payload.get("uid")
    return uid if isinstance(uid, str) and uid.startswith("usr_") and len(uid) <= 80 else None


def create_oauth_state(settings: Settings, now: int | None = None) -> tuple[str, str]:
    if not settings.session_secret:
        raise AuthError(503, "auth_unavailable", "로그인을 현재 사용할 수 없습니다.")
    issued = int(time.time()) if now is None else now
    state = secrets.token_urlsafe(24)
    signed = _signed_token(
        settings.session_secret,
        "padiem-chat/oauth-state/v1",
        {"v": 1, "state": state, "exp": issued + OAUTH_STATE_MAX_AGE_SECONDS},
    )
    return state, signed


def verify_oauth_state(settings: Settings, query_state: str | None, cookie_token: str | None, now: int | None = None) -> bool:
    if not query_state or not cookie_token or not settings.session_secret:
        return False
    payload = _verify_token(settings.session_secret, "padiem-chat/oauth-state/v1", cookie_token, now=now)
    if not payload or payload.get("v") != 1:
        return False
    expected = payload.get("state")
    return isinstance(expected, str) and secrets.compare_digest(expected, query_state)


def session_cookie_kwargs(settings: Settings) -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": "/",
        "max_age": settings.session_max_age_seconds,
    }


def oauth_state_cookie_kwargs() -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "path": "/",
        "max_age": OAUTH_STATE_MAX_AGE_SECONDS,
    }


class GoogleOAuthClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    @property
    def redirect_uri(self) -> str:
        if not self.settings.public_base_url:
            raise AuthError(503, "auth_unavailable", "로그인을 현재 사용할 수 없습니다.")
        return self.settings.public_base_url.rstrip("/") + "/auth/google/callback"

    def authorization_url(self, state: str) -> str:
        if not self.settings.google_client_id:
            raise AuthError(503, "auth_unavailable", "로그인을 현재 사용할 수 없습니다.")
        params = {
            "client_id": self.settings.google_client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "include_granted_scopes": "true",
        }
        return GOOGLE_AUTH_URL + "?" + urlencode(params)

    async def _bounded_json(self, response: httpx.Response) -> dict[str, Any]:
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            if len(raw) + len(chunk) > MAX_AUTH_RESPONSE_BYTES:
                raise AuthError(502, "auth_provider_error", "Google 로그인 응답을 확인하지 못했습니다.")
            raw.extend(chunk)
        if response.status_code < 200 or response.status_code >= 300:
            raise AuthError(502, "auth_provider_error", "Google 로그인에 연결하지 못했습니다.")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthError(502, "auth_provider_error", "Google 로그인 응답을 확인하지 못했습니다.") from exc
        if not isinstance(data, dict):
            raise AuthError(502, "auth_provider_error", "Google 로그인 응답을 확인하지 못했습니다.")
        return data

    async def exchange_code(self, code: str) -> str:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise AuthError(503, "auth_unavailable", "로그인을 현재 사용할 수 없습니다.")
        timeout = httpx.Timeout(15.0, connect=8.0)
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=timeout, follow_redirects=False) as client:
                async with client.stream(
                    "POST",
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": self.settings.google_client_id,
                        "client_secret": self.settings.google_client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.redirect_uri,
                    },
                ) as response:
                    data = await self._bounded_json(response)
        except AuthError:
            raise
        except httpx.HTTPError as exc:
            raise AuthError(502, "auth_provider_error", "Google 로그인에 연결하지 못했습니다.") from exc
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthError(502, "auth_provider_error", "Google 로그인 응답을 확인하지 못했습니다.")
        return token

    async def fetch_userinfo(self, access_token: str) -> dict[str, str]:
        timeout = httpx.Timeout(15.0, connect=8.0)
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=timeout, follow_redirects=False) as client:
                async with client.stream(
                    "GET",
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                ) as response:
                    data = await self._bounded_json(response)
        except AuthError:
            raise
        except httpx.HTTPError as exc:
            raise AuthError(502, "auth_provider_error", "Google 사용자 정보를 확인하지 못했습니다.") from exc
        subject = data.get("id")
        email = data.get("email")
        verified = data.get("verified_email")
        name = data.get("name")
        picture = data.get("picture")
        if not isinstance(subject, str) or not subject or not isinstance(email, str) or not email or verified is not True:
            raise AuthError(403, "auth_identity_unverified", "확인된 Google 계정으로 로그인해 주세요.")
        return {
            "subject": subject[:255],
            "email": email[:320],
            "name": name[:160] if isinstance(name, str) else "",
            "picture": picture[:1000] if isinstance(picture, str) else "",
        }
