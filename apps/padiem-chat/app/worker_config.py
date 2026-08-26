from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .config import Settings

WORKER_BINDING_NAMES = frozenset({
    "PADIEM_CHAT_RUNTIME_MODE",
    "PADIEM_CHAT_B14_BASE_URL",
    "PADIEM_CHAT_TIMEOUT_SECONDS",
    "PADIEM_CHAT_LIVE_ENABLED",
    "PADIEM_CHAT_WEB_PROVIDER",
    "FIRECRAWL_API_KEY",
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

BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
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
