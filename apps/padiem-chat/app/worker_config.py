from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .config import Settings

WORKER_BINDING_NAMES = frozenset({
    "PADIEM_CHAT_RUNTIME_MODE",
    "PADIEM_CHAT_B14_BASE_URL",
    "PADIEM_CHAT_TIMEOUT_SECONDS",
    "PADIEM_CHAT_WEB_PROVIDER",
    "FIRECRAWL_API_KEY",
    "PADIEM_CHAT_WEB_TIMEOUT_SECONDS",
})

BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def _binding_value(env: Any, key: str) -> Any:
    if isinstance(env, Mapping):
        return env.get(key)
    return getattr(env, key, None)


def settings_from_worker_bindings(env: Any) -> Settings:
    return Settings.from_values(
        runtime_mode=_binding_value(env, "PADIEM_CHAT_RUNTIME_MODE") or "mock",
        b14_base_url=_binding_value(env, "PADIEM_CHAT_B14_BASE_URL"),
        timeout_seconds=_binding_value(env, "PADIEM_CHAT_TIMEOUT_SECONDS") or "20",
        web_provider=_binding_value(env, "PADIEM_CHAT_WEB_PROVIDER") or "off",
        firecrawl_api_key=_binding_value(env, "FIRECRAWL_API_KEY"),
        web_timeout_seconds=_binding_value(env, "PADIEM_CHAT_WEB_TIMEOUT_SECONDS") or "15",
    )


def response_headers_for_path(path: str) -> dict[str, str]:
    headers = dict(BASE_SECURITY_HEADERS)
    if path == "/health" or path.startswith("/api/"):
        headers["Cache-Control"] = "no-store"
    return headers
