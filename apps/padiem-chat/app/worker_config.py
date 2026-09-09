from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .config import Settings

WORKER_BINDING_NAMES = frozenset({
    "PADIEM_CHAT_RUNTIME_MODE",
    "PADIEM_CHAT_B14_BASE_URL",
    "PADIEM_CHAT_TIMEOUT_SECONDS",
    "PADIEM_CHAT_LIVE_ENABLED",
    "PADIEM_CHAT_WEB_PROVIDER",
    "FIRECRAWL_API_KEY",
    "PADIEM_CHAT_DAUM_REST_API_KEY",
    "PADIEM_CHAT_WEB_TIMEOUT_SECONDS",
    "PADIEM_CHAT_AUTH_MODE",
    "PADIEM_CHAT_PUBLIC_BASE_URL",
    "PADIEM_CHAT_GOOGLE_CLIENT_ID",
    "PADIEM_CHAT_GOOGLE_CLIENT_SECRET",
    "PADIEM_CHAT_SESSION_SECRET",
    "PADIEM_CHAT_SESSION_MAX_AGE_SECONDS",
    "PADIEM_CHAT_QUOTA_SALT",
    "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT",
    "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT",
    "PADIEM_CHAT_USER_BURST_LIMIT",
    "PADIEM_CHAT_USER_DAILY_LIMIT",
    "PADIEM_CHAT_GLOBAL_DAILY_LIMIT",
})
D1_BINDING_NAME = "PADIEM_CHAT_DB"
B14_SERVICE_BINDING_NAME = "B14_SERVICE"
IDENTITY_AUTHORITY_SERVICE_BINDING_NAME = "IDENTITY_AUTHORITY_SERVICE"
WORKSPACE_R2_BINDING_NAME = "PADIEM_WORKSPACE_FILES"

# Worker-native P01/Engine configuration surface (#2229). Owned by B62 deployment
# composition and read only from trusted Worker bindings — never from os.environ
# and never from browser/request input. The Engine target is the fixed
# ``P01_ENGINE_SERVICE`` Service Binding; caller identity/credential are
# server/deployment-owned. Missing or malformed values fail closed.
P01_ENGINE_SERVICE_BINDING_NAME = "P01_ENGINE_SERVICE"
P01_ENGINE_CALLER_ID_ENV = "P01_ENGINE_CALLER_ID"
P01_ENGINE_CREDENTIAL_ENV = "P01_ENGINE_CREDENTIAL"
P01_ENGINE_BINDING_NAMES = frozenset({
    P01_ENGINE_SERVICE_BINDING_NAME,
    P01_ENGINE_CALLER_ID_ENV,
    P01_ENGINE_CREDENTIAL_ENV,
})
_P01_CALLER_ID_MAX = 64
_P01_CREDENTIAL_MIN_BYTES = 32
_P01_CREDENTIAL_MAX_BYTES = 512
_P01_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "frame-ancestors 'none'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com; "
    "form-action 'self'"
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"

BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Permissions-Policy": PERMISSIONS_POLICY,
}


def binding_value(env: Any, key: str) -> Any:
    if isinstance(env, Mapping):
        return env.get(key)
    return getattr(env, key, None)


def settings_from_worker_bindings(env: Any) -> Settings:
    return Settings.from_values(
        runtime_mode=binding_value(env, "PADIEM_CHAT_RUNTIME_MODE") or "mock",
        b14_base_url=binding_value(env, "PADIEM_CHAT_B14_BASE_URL"),
        timeout_seconds=binding_value(env, "PADIEM_CHAT_TIMEOUT_SECONDS") or "20",
        live_enabled=binding_value(env, "PADIEM_CHAT_LIVE_ENABLED") or "false",
        web_provider=binding_value(env, "PADIEM_CHAT_WEB_PROVIDER") or "off",
        firecrawl_api_key=binding_value(env, "FIRECRAWL_API_KEY"),
        daum_rest_api_key=binding_value(env, "PADIEM_CHAT_DAUM_REST_API_KEY"),
        web_timeout_seconds=binding_value(env, "PADIEM_CHAT_WEB_TIMEOUT_SECONDS") or "15",
        auth_mode=binding_value(env, "PADIEM_CHAT_AUTH_MODE") or "off",
        public_base_url=binding_value(env, "PADIEM_CHAT_PUBLIC_BASE_URL"),
        google_client_id=binding_value(env, "PADIEM_CHAT_GOOGLE_CLIENT_ID"),
        google_client_secret=binding_value(env, "PADIEM_CHAT_GOOGLE_CLIENT_SECRET"),
        session_secret=binding_value(env, "PADIEM_CHAT_SESSION_SECRET"),
        session_max_age_seconds=binding_value(env, "PADIEM_CHAT_SESSION_MAX_AGE_SECONDS") or str(7 * 24 * 3600),
        quota_salt=binding_value(env, "PADIEM_CHAT_QUOTA_SALT"),
        anonymous_burst_limit=binding_value(env, "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT") or "4",
        anonymous_daily_limit=binding_value(env, "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT") or "20",
        user_burst_limit=binding_value(env, "PADIEM_CHAT_USER_BURST_LIMIT") or "8",
        user_daily_limit=binding_value(env, "PADIEM_CHAT_USER_DAILY_LIMIT") or "100",
        global_daily_limit=binding_value(env, "PADIEM_CHAT_GLOBAL_DAILY_LIMIT") or "1000",
    )


@dataclass(frozen=True, slots=True)
class P01EngineWorkerConfig:
    service_binding: Any = field(repr=False)
    caller_id: str
    credential: str = field(repr=False)


def p01_engine_config_from_worker_bindings(env: Any) -> P01EngineWorkerConfig | None:
    """Project the Worker-native P01/Engine surface from trusted bindings.

    Returns ``None`` (fail closed, before any transport) unless the Engine
    Service Binding is present and both server-owned caller values are well
    formed. Never consults ``os.environ``.
    """
    service_binding = binding_value(env, P01_ENGINE_SERVICE_BINDING_NAME)
    raw_caller = binding_value(env, P01_ENGINE_CALLER_ID_ENV)
    raw_credential = binding_value(env, P01_ENGINE_CREDENTIAL_ENV)
    caller_id = raw_caller.strip() if isinstance(raw_caller, str) else ""
    credential = raw_credential if isinstance(raw_credential, str) else ""

    if service_binding is None and not caller_id and not credential:
        return None
    if service_binding is None:
        return None
    if (
        not caller_id
        or len(caller_id) > _P01_CALLER_ID_MAX
        or not _P01_SAFE_ID_RE.fullmatch(caller_id)
    ):
        return None
    credential_bytes = len(credential.encode("utf-8"))
    if not _P01_CREDENTIAL_MIN_BYTES <= credential_bytes <= _P01_CREDENTIAL_MAX_BYTES:
        return None
    return P01EngineWorkerConfig(
        service_binding=service_binding,
        caller_id=caller_id,
        credential=credential,
    )


def apply_live_deadman_switch(settings: Settings) -> Settings:
    """Keep the public Worker on mock unless live execution is explicitly armed.

    B14 may be configured or independently live for owner verification without that
    implicitly exposing public B62 live execution. The switch is deployment-owned
    and browser input cannot influence it.
    """
    if settings.runtime_mode == "b14" and not settings.live_enabled:
        return replace(settings, runtime_mode="mock")
    return settings


def response_headers_for_path(path: str) -> dict[str, str]:
    headers = dict(BASE_SECURITY_HEADERS)
    if path == "/health" or path.startswith("/api/") or path.startswith("/auth/"):
        headers["Cache-Control"] = "no-store"
    return headers
