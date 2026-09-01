from __future__ import annotations

from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit, urlunsplit


class ConfigError(ValueError):
    pass


def _normalize_base_url(value: str, *, https_only: bool = False, root_only: bool = False) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    allowed = {"https"} if https_only else {"http", "https"}
    if parsed.scheme not in allowed:
        scheme_label = "https" if https_only else "http or https"
        raise ConfigError(f"base URL must use {scheme_label}")
    if not parsed.hostname:
        raise ConfigError("base URL must include a host")
    if parsed.username or parsed.password:
        raise ConfigError("base URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise ConfigError("base URL must not include query or fragment")
    path = parsed.path.rstrip("/")
    if root_only and path:
        raise ConfigError("public base URL must not include a path")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _bounded_int(value: object, *, name: str, minimum: int = 1, maximum: int = 1_000_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _strict_bool(value: object, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ConfigError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    runtime_mode: str = "mock"
    b14_base_url: str | None = None
    timeout_seconds: float = 20.0
    live_enabled: bool = False
    web_provider: str = "off"
    firecrawl_api_key: str | None = field(default=None, repr=False)
    daum_rest_api_key: str | None = field(default=None, repr=False)
    web_timeout_seconds: float = 15.0
    auth_mode: str = "off"
    public_base_url: str | None = None
    google_client_id: str | None = field(default=None, repr=False)
    google_client_secret: str | None = field(default=None, repr=False)
    session_secret: str | None = field(default=None, repr=False)
    session_max_age_seconds: int = 7 * 24 * 3600
    quota_salt: str | None = field(default=None, repr=False)
    anonymous_burst_limit: int = 4
    anonymous_daily_limit: int = 20
    user_burst_limit: int = 8
    user_daily_limit: int = 100
    global_daily_limit: int = 1000

    @classmethod
    def from_values(
        cls,
        runtime_mode: object = "mock",
        b14_base_url: object = None,
        timeout_seconds: object = 20.0,
        live_enabled: object = False,
        web_provider: object = "off",
        firecrawl_api_key: object = None,
        daum_rest_api_key: object = None,
        web_timeout_seconds: object = 15.0,
        auth_mode: object = "off",
        public_base_url: object = None,
        google_client_id: object = None,
        google_client_secret: object = None,
        session_secret: object = None,
        session_max_age_seconds: object = 7 * 24 * 3600,
        quota_salt: object = None,
        anonymous_burst_limit: object = 4,
        anonymous_daily_limit: object = 20,
        user_burst_limit: object = 8,
        user_daily_limit: object = 100,
        global_daily_limit: object = 1000,
    ) -> "Settings":
        mode = str(runtime_mode or "mock").strip().lower()
        if mode not in {"mock", "b14"}:
            raise ConfigError("PADIEM_CHAT_RUNTIME_MODE must be mock or b14")

        raw_base = "" if b14_base_url is None else str(b14_base_url).strip()
        base = _normalize_base_url(raw_base) if raw_base else None
        if mode == "b14" and base is None:
            raise ConfigError("PADIEM_CHAT_B14_BASE_URL is required in b14 mode")

        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigError("PADIEM_CHAT_TIMEOUT_SECONDS must be numeric") from exc
        if not 1 <= timeout <= 60:
            raise ConfigError("PADIEM_CHAT_TIMEOUT_SECONDS must be between 1 and 60")

        live = _strict_bool(live_enabled, name="PADIEM_CHAT_LIVE_ENABLED")

        web = str(web_provider or "off").strip().lower()
        if web not in {"off", "mock", "firecrawl", "daum"}:
            raise ConfigError("PADIEM_CHAT_WEB_PROVIDER must be off, mock, firecrawl, or daum")
        raw_firecrawl_key = "" if firecrawl_api_key is None else str(firecrawl_api_key).strip()
        firecrawl_key = raw_firecrawl_key or None
        if web == "firecrawl" and firecrawl_key is None:
            raise ConfigError("FIRECRAWL_API_KEY is required when PADIEM_CHAT_WEB_PROVIDER=firecrawl")
        raw_daum_key = "" if daum_rest_api_key is None else str(daum_rest_api_key).strip()
        daum_key = raw_daum_key or None
        if web == "daum" and daum_key is None:
            raise ConfigError("PADIEM_CHAT_DAUM_REST_API_KEY is required when PADIEM_CHAT_WEB_PROVIDER=daum")

        try:
            web_timeout = float(web_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigError("PADIEM_CHAT_WEB_TIMEOUT_SECONDS must be numeric") from exc
        if not 1 <= web_timeout <= 30:
            raise ConfigError("PADIEM_CHAT_WEB_TIMEOUT_SECONDS must be between 1 and 30")

        auth = str(auth_mode or "off").strip().lower()
        if auth not in {"off", "google"}:
            raise ConfigError("PADIEM_CHAT_AUTH_MODE must be off or google")
        raw_public = "" if public_base_url is None else str(public_base_url).strip()
        public = _normalize_base_url(raw_public, https_only=True, root_only=True) if raw_public else None
        client_id = str(google_client_id or "").strip() or None
        client_secret = str(google_client_secret or "").strip() or None
        secret = str(session_secret or "").strip() or None
        try:
            max_age = int(session_max_age_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigError("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS must be an integer") from exc
        if not 300 <= max_age <= 30 * 24 * 3600:
            raise ConfigError("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS must be between 300 and 2592000")
        if auth == "google":
            if public is None:
                raise ConfigError("PADIEM_CHAT_PUBLIC_BASE_URL is required in google auth mode")
            if client_id is None:
                raise ConfigError("PADIEM_CHAT_GOOGLE_CLIENT_ID is required in google auth mode")
            if client_secret is None:
                raise ConfigError("PADIEM_CHAT_GOOGLE_CLIENT_SECRET is required in google auth mode")
            if secret is None or len(secret) < 32:
                raise ConfigError("PADIEM_CHAT_SESSION_SECRET must be at least 32 characters in google auth mode")

        raw_quota_salt = "" if quota_salt is None else str(quota_salt).strip()
        normalized_quota_salt = raw_quota_salt or None
        if normalized_quota_salt is not None and len(normalized_quota_salt) < 32:
            raise ConfigError("PADIEM_CHAT_QUOTA_SALT must be at least 32 characters when configured")

        anon_burst = _bounded_int(
            anonymous_burst_limit,
            name="PADIEM_CHAT_ANONYMOUS_BURST_LIMIT",
        )
        anon_daily = _bounded_int(
            anonymous_daily_limit,
            name="PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT",
        )
        signed_burst = _bounded_int(
            user_burst_limit,
            name="PADIEM_CHAT_USER_BURST_LIMIT",
        )
        signed_daily = _bounded_int(
            user_daily_limit,
            name="PADIEM_CHAT_USER_DAILY_LIMIT",
        )
        global_daily = _bounded_int(
            global_daily_limit,
            name="PADIEM_CHAT_GLOBAL_DAILY_LIMIT",
            maximum=10_000_000,
        )

        return cls(
            runtime_mode=mode,
            b14_base_url=base,
            timeout_seconds=timeout,
            live_enabled=live,
            web_provider=web,
            firecrawl_api_key=firecrawl_key,
            daum_rest_api_key=daum_key,
            web_timeout_seconds=web_timeout,
            auth_mode=auth,
            public_base_url=public,
            google_client_id=client_id,
            google_client_secret=client_secret,
            session_secret=secret,
            session_max_age_seconds=max_age,
            quota_salt=normalized_quota_salt,
            anonymous_burst_limit=anon_burst,
            anonymous_daily_limit=anon_daily,
            user_burst_limit=signed_burst,
            user_daily_limit=signed_daily,
            global_daily_limit=global_daily,
        )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls.from_values(
            runtime_mode=os.getenv("PADIEM_CHAT_RUNTIME_MODE", "mock"),
            b14_base_url=os.getenv("PADIEM_CHAT_B14_BASE_URL"),
            timeout_seconds=os.getenv("PADIEM_CHAT_TIMEOUT_SECONDS", "20"),
            live_enabled=os.getenv("PADIEM_CHAT_LIVE_ENABLED", "false"),
            web_provider=os.getenv("PADIEM_CHAT_WEB_PROVIDER", "off"),
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY"),
            daum_rest_api_key=os.getenv("PADIEM_CHAT_DAUM_REST_API_KEY"),
            web_timeout_seconds=os.getenv("PADIEM_CHAT_WEB_TIMEOUT_SECONDS", "15"),
            auth_mode=os.getenv("PADIEM_CHAT_AUTH_MODE", "off"),
            public_base_url=os.getenv("PADIEM_CHAT_PUBLIC_BASE_URL"),
            google_client_id=os.getenv("PADIEM_CHAT_GOOGLE_CLIENT_ID"),
            google_client_secret=os.getenv("PADIEM_CHAT_GOOGLE_CLIENT_SECRET"),
            session_secret=os.getenv("PADIEM_CHAT_SESSION_SECRET"),
            session_max_age_seconds=os.getenv("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS", str(7 * 24 * 3600)),
            quota_salt=os.getenv("PADIEM_CHAT_QUOTA_SALT"),
            anonymous_burst_limit=os.getenv("PADIEM_CHAT_ANONYMOUS_BURST_LIMIT", "4"),
            anonymous_daily_limit=os.getenv("PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT", "20"),
            user_burst_limit=os.getenv("PADIEM_CHAT_USER_BURST_LIMIT", "8"),
            user_daily_limit=os.getenv("PADIEM_CHAT_USER_DAILY_LIMIT", "100"),
            global_daily_limit=os.getenv("PADIEM_CHAT_GLOBAL_DAILY_LIMIT", "1000"),
        )
