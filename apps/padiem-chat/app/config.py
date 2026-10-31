from __future__ import annotations

from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit, urlunsplit


class ConfigError(ValueError):
    pass


#: Hosts the explicit local-development flag may serve over plain loopback
#: HTTP (#5573 stage 2). Nothing else ever reaches this set: production
#: validation stays https-only, and the Worker binding path never sets
#: `local_dev` (see app/worker_config.py — it calls Settings.from_values
#: without the flag, so the default False holds on Cloudflare).
LOCAL_DEV_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _normalize_base_url(
    value: str,
    *,
    https_only: bool = False,
    root_only: bool = False,
    allow_loopback_http: bool = False,
) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    allowed = {"https"} if https_only else {"http", "https"}
    if parsed.scheme not in allowed:
        # The one exception: a loopback HTTP base the caller explicitly opted
        # into via PADIEM_LOCAL_DEV=1. Same strictness otherwise — a non-
        # loopback http:// base is still refused even with the flag set.
        if (
            allow_loopback_http
            and parsed.scheme == "http"
            and (parsed.hostname or "") in LOCAL_DEV_LOOPBACK_HOSTS
        ):
            pass
        else:
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


def _optional_secret(value: object, *, name: str, minimum: int = 32) -> str | None:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return None
    if len(raw) < minimum:
        raise ConfigError(f"{name} must be at least {minimum} characters when configured")
    return raw


def _secret_list(value: object, *, name: str, minimum: int = 32) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, (list, tuple)):
        candidates = [str(item) for item in value]
    else:
        raise ConfigError(f"{name} must be a comma-separated list")
    result: list[str] = []
    for candidate in candidates:
        secret = candidate.strip()
        if not secret:
            continue
        if len(secret) < minimum:
            raise ConfigError(
                f"{name} entries must be at least {minimum} characters when configured"
            )
        if secret not in result:
            result.append(secret)
    return tuple(result)


@dataclass(frozen=True)
class Settings:
    runtime_mode: str = "mock"
    b14_base_url: str | None = None
    # #5784: "binding" (default) reaches the Worker through the Service Binding;
    # "https" reaches the same contract over the Tunnel host. Nothing else about
    # the call changes, including the caller proof.
    b14_upstream_mode: str = "binding"
    b66_quote_base_url: str | None = None
    file_lane_origin: str | None = None
    file_lane_ticket_secret: str | None = field(default=None, repr=False)
    timeout_seconds: float = 600.0
    completed_timeout_seconds: float = 600.0
    live_enabled: bool = False
    web_provider: str = "off"
    firecrawl_api_key: str | None = field(default=None, repr=False)
    daum_rest_api_key: str | None = field(default=None, repr=False)
    tinyfish_api_key: str | None = field(default=None, repr=False)
    web_timeout_seconds: float = 30.0
    auth_mode: str = "off"
    public_base_url: str | None = None
    google_client_id: str | None = field(default=None, repr=False)
    google_client_secret: str | None = field(default=None, repr=False)
    session_secret: str | None = field(default=None, repr=False)
    # #5121: PADIEM Custom credentials use their own encryption secret and key
    # purpose. The previous/legacy rings exist only for staged migration.
    byok_via_b14: bool = False
    custom_key_secret: str | None = field(default=None, repr=False)
    custom_key_previous_secrets: tuple[str, ...] = field(default=(), repr=False)
    custom_key_legacy_session_secrets: tuple[str, ...] = field(default=(), repr=False)
    session_max_age_seconds: int = 7 * 24 * 3600
    # #5115: padiem-glass loopback HTTP deployments set this False so the
    # session cookie survives the native CPython server on 127.0.0.1. The
    # Cloudflare deployment keeps the default True behind its TLS edge.
    cookie_secure: bool = True
    quota_salt: str | None = field(default=None, repr=False)
    anonymous_burst_limit: int = 4
    anonymous_daily_limit: int = 20
    user_burst_limit: int = 8
    user_daily_limit: int = 100
    global_daily_limit: int = 1000
    # #5573 stage 2: explicit local-run opt-in (PADIEM_LOCAL_DEV=1). Enables
    # loopback HTTP for the public base URL and the same-origin expectation.
    # Default False — every production deployment keeps the https-only rules.
    local_dev: bool = False

    @classmethod
    def from_values(
        cls,
        runtime_mode: object = "mock",
        b14_base_url: object = None,
        timeout_seconds: object = 600.0,
        completed_timeout_seconds: object = 600.0,
        live_enabled: object = False,
        web_provider: object = "off",
        firecrawl_api_key: object = None,
        daum_rest_api_key: object = None,
        tinyfish_api_key: object = None,
        web_timeout_seconds: object = 30.0,
        auth_mode: object = "off",
        public_base_url: object = None,
        google_client_id: object = None,
        google_client_secret: object = None,
        session_secret: object = None,
        byok_via_b14: object = False,
        custom_key_secret: object = None,
        custom_key_previous_secrets: object = None,
        custom_key_legacy_session_secrets: object = None,
        session_max_age_seconds: object = 7 * 24 * 3600,
        cookie_secure: object = True,
        quota_salt: object = None,
        anonymous_burst_limit: object = 4,
        anonymous_daily_limit: object = 20,
        user_burst_limit: object = 8,
        user_daily_limit: object = 100,
        global_daily_limit: object = 1000,
        b66_quote_base_url: object = None,
        file_lane_origin: object = None,
        file_lane_ticket_secret: object = None,
        # #5784: appended last so every existing positional caller is untouched.
        b14_upstream_mode: object = None,
        b14_upstream_url: object = None,
        # #5573 stage 2: also appended last — the local-run opt-in.
        local_dev: object = None,
    ) -> "Settings":
        mode = str(runtime_mode or "mock").strip().lower()
        if mode not in {"mock", "b14"}:
            raise ConfigError("PADIEM_CHAT_RUNTIME_MODE must be mock or b14")

        # The flag is deliberately narrow: "1"/"true" enable, "0"/"false"/unset
        # disable, and anything else raises so a typo never silently flips a
        # production run into the loopback allowance (or a local run off it).
        raw_local_dev = "" if local_dev is None else str(local_dev).strip().lower()
        if raw_local_dev in {"", "0", "false"}:
            local = False
        elif raw_local_dev in {"1", "true"}:
            local = True
        else:
            raise ConfigError("PADIEM_LOCAL_DEV must be 1 or 0")

        raw_base = "" if b14_base_url is None else str(b14_base_url).strip()
        base = _normalize_base_url(raw_base) if raw_base else None
        # #5784: one deployment variable chooses which B14 this Worker talks to.
        # Unset means the Service Binding, and the origin stays what it is today.
        from padiem_ai_core.b14_upstream import (
            UPSTREAM_MODE_ENV,
            UPSTREAM_URL_ENV,
            B14UpstreamConfigError,
            resolve_b14_upstream,
        )

        try:
            upstream = resolve_b14_upstream({
                UPSTREAM_MODE_ENV: "" if b14_upstream_mode is None else str(b14_upstream_mode),
                UPSTREAM_URL_ENV: "" if b14_upstream_url is None else str(b14_upstream_url),
            })
        except B14UpstreamConfigError as exc:
            raise ConfigError(exc.code) from None
        if upstream.uses_https:
            if base is not None and base != upstream.origin:
                # An old binding-mode base URL left beside a flipped switch is a
                # half-applied change; refusing beats picking one of the two.
                raise ConfigError("PADIEM_CHAT_B14_BASE_URL conflicts with B14_UPSTREAM_URL")
            base = upstream.origin
        if mode == "b14" and base is None:
            raise ConfigError("PADIEM_CHAT_B14_BASE_URL is required in b14 mode")

        raw_b66_quote = "" if b66_quote_base_url is None else str(b66_quote_base_url).strip()
        b66_quote = (
            _normalize_base_url(raw_b66_quote, https_only=True, root_only=True)
            if raw_b66_quote
            else None
        )

        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigError("PADIEM_CHAT_TIMEOUT_SECONDS must be numeric") from exc
        if not 1 <= timeout <= 3600:
            raise ConfigError("PADIEM_CHAT_TIMEOUT_SECONDS must be between 1 and 3600")

        try:
            completed_timeout = float(completed_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigError("PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS must be numeric") from exc
        if not 1 <= completed_timeout <= 3600:
            raise ConfigError("PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS must be between 1 and 3600")

        live = _strict_bool(live_enabled, name="PADIEM_CHAT_LIVE_ENABLED")

        web = str(web_provider or "off").strip().lower()
        if web not in {"off", "mock", "firecrawl", "daum", "tinyfish", "tinyfish_daum"}:
            raise ConfigError(
                "PADIEM_CHAT_WEB_PROVIDER must be off, mock, firecrawl, daum, tinyfish, or tinyfish_daum"
            )
        raw_firecrawl_key = "" if firecrawl_api_key is None else str(firecrawl_api_key).strip()
        firecrawl_key = raw_firecrawl_key or None
        if web == "firecrawl" and firecrawl_key is None:
            raise ConfigError("FIRECRAWL_API_KEY is required when PADIEM_CHAT_WEB_PROVIDER=firecrawl")
        raw_daum_key = "" if daum_rest_api_key is None else str(daum_rest_api_key).strip()
        daum_key = raw_daum_key or None
        if web in {"daum", "tinyfish_daum"} and daum_key is None:
            raise ConfigError("PADIEM_CHAT_DAUM_REST_API_KEY is required when PADIEM_CHAT_WEB_PROVIDER=daum")
        # #3385: TinyFish-first / Daum-after-quota is explicitly Owner-approved.
        # Both credentials are required; missing binding is never a reason to
        # silently switch provider or treat a failed production search as off.
        raw_tinyfish_key = "" if tinyfish_api_key is None else str(tinyfish_api_key).strip()
        tinyfish_key = raw_tinyfish_key or None
        if web in {"tinyfish", "tinyfish_daum"} and tinyfish_key is None:
            raise ConfigError("TINYFISH_API_KEY is required when PADIEM_CHAT_WEB_PROVIDER=tinyfish")

        try:
            web_timeout = float(web_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigError("PADIEM_CHAT_WEB_TIMEOUT_SECONDS must be numeric") from exc
        if not 1 <= web_timeout <= 60:
            raise ConfigError("PADIEM_CHAT_WEB_TIMEOUT_SECONDS must be between 1 and 60")

        auth = str(auth_mode or "off").strip().lower()
        if auth not in {"off", "google", "password", "hybrid"}:
            raise ConfigError("PADIEM_CHAT_AUTH_MODE must be off, google, password, or hybrid")
        raw_public = "" if public_base_url is None else str(public_base_url).strip()
        public = (
            _normalize_base_url(
                raw_public, https_only=True, root_only=True, allow_loopback_http=local
            )
            if raw_public
            else None
        )
        client_id = str(google_client_id or "").strip() or None
        client_secret = str(google_client_secret or "").strip() or None
        secret = str(session_secret or "").strip() or None
        custom_key = _optional_secret(
            custom_key_secret, name="PADIEM_CHAT_CUSTOM_KEY_SECRET"
        )
        previous_custom_keys = _secret_list(
            custom_key_previous_secrets,
            name="PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS",
        )
        legacy_custom_keys = _secret_list(
            custom_key_legacy_session_secrets,
            name="PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS",
        )
        try:
            max_age = int(session_max_age_seconds)
        except (TypeError, ValueError) as exc:
            raise ConfigError("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS must be an integer") from exc
        # #5115: the session cookie's Secure flag is deployment-owned. The
        # Cloudflare deployment keeps True behind its TLS edge; the COM2
        # loopback HTTP runtime sets False so the native server holds a
        # session across requests.
        if isinstance(cookie_secure, bool):
            cookie_secure_value = cookie_secure
        else:
            cookie_secure_value = str(cookie_secure).strip().lower()
            if cookie_secure_value in {"true", "1", "yes", "on"}:
                cookie_secure_value = True
            elif cookie_secure_value in {"false", "0", "no", "off"}:
                cookie_secure_value = False
            else:
                raise ConfigError(
                    "PADIEM_CHAT_COOKIE_SECURE must be true or false"
                ) from None
        if not 300 <= max_age <= 30 * 24 * 3600:
            raise ConfigError("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS must be between 300 and 2592000")
        if auth != "off":
            if public is None:
                raise ConfigError("PADIEM_CHAT_PUBLIC_BASE_URL is required when authentication is enabled")
            if secret is None or len(secret) < 32:
                raise ConfigError("PADIEM_CHAT_SESSION_SECRET must be at least 32 characters when authentication is enabled")
        if auth in {"google", "hybrid"}:
            if client_id is None:
                raise ConfigError("PADIEM_CHAT_GOOGLE_CLIENT_ID is required when Google authentication is enabled")
            if client_secret is None:
                raise ConfigError("PADIEM_CHAT_GOOGLE_CLIENT_SECRET is required when Google authentication is enabled")

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
            file_lane_origin=_normalize_base_url(str(file_lane_origin), https_only=True, root_only=True) if file_lane_origin else None,
            file_lane_ticket_secret=_optional_secret(file_lane_ticket_secret, name="file_lane_ticket_secret"),
            b14_base_url=base,
            b14_upstream_mode=upstream.mode,
            b66_quote_base_url=b66_quote,
            timeout_seconds=timeout,
            completed_timeout_seconds=completed_timeout,
            live_enabled=live,
            web_provider=web,
            firecrawl_api_key=firecrawl_key,
            daum_rest_api_key=daum_key,
            tinyfish_api_key=tinyfish_key,
            web_timeout_seconds=web_timeout,
            auth_mode=auth,
            public_base_url=public,
            google_client_id=client_id,
            google_client_secret=client_secret,
            session_secret=secret,
            byok_via_b14=_strict_bool(byok_via_b14, name="BYOK_VIA_B14"),
            custom_key_secret=custom_key,
            custom_key_previous_secrets=previous_custom_keys,
            custom_key_legacy_session_secrets=legacy_custom_keys,
            session_max_age_seconds=max_age,
            cookie_secure=cookie_secure_value,
            quota_salt=normalized_quota_salt,
            anonymous_burst_limit=anon_burst,
            anonymous_daily_limit=anon_daily,
            user_burst_limit=signed_burst,
            user_daily_limit=signed_daily,
            global_daily_limit=global_daily,
            local_dev=local,
        )

    @classmethod
    def from_env(cls) -> "Settings":
        runtime_mode = os.getenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
        # A real B14 session defaults to the Owner's two-provider search policy.
        # An explicitly configured provider (including "off") wins; mock and
        # offline default to off, preserving zero-network development runs.
        configured_provider = os.getenv("PADIEM_CHAT_WEB_PROVIDER")
        live_enabled = os.getenv("PADIEM_CHAT_LIVE_ENABLED", "false")
        default_provider = (
            "tinyfish_daum"
            if runtime_mode.strip().lower() == "b14"
            and live_enabled.strip().lower() == "true"
            else "off"
        )
        return cls.from_values(
            runtime_mode=runtime_mode,
            file_lane_origin=os.getenv("PADIEM_CHAT_FILE_LANE_ORIGIN"),
            file_lane_ticket_secret=os.getenv("PADIEM_CHAT_FILE_LANE_TICKET_SECRET"),
            b14_base_url=os.getenv("PADIEM_CHAT_B14_BASE_URL"),
            b14_upstream_mode=os.getenv("B14_UPSTREAM_MODE"),
            b14_upstream_url=os.getenv("B14_UPSTREAM_URL"),
            b66_quote_base_url=os.getenv("PADIEM_CHAT_B66_QUOTE_BASE_URL"),
            timeout_seconds=os.getenv("PADIEM_CHAT_TIMEOUT_SECONDS", "600"),
            completed_timeout_seconds=os.getenv("PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS", "600"),
            live_enabled=os.getenv("PADIEM_CHAT_LIVE_ENABLED", "false"),
            web_provider=(default_provider if configured_provider is None else configured_provider),
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY"),
            daum_rest_api_key=os.getenv("PADIEM_CHAT_DAUM_REST_API_KEY"),
            tinyfish_api_key=os.getenv("TINYFISH_API_KEY"),
            web_timeout_seconds=os.getenv("PADIEM_CHAT_WEB_TIMEOUT_SECONDS", "30"),
            auth_mode=os.getenv("PADIEM_CHAT_AUTH_MODE", "off"),
            public_base_url=os.getenv("PADIEM_CHAT_PUBLIC_BASE_URL"),
            google_client_id=os.getenv("PADIEM_CHAT_GOOGLE_CLIENT_ID"),
            google_client_secret=os.getenv("PADIEM_CHAT_GOOGLE_CLIENT_SECRET"),
            session_secret=os.getenv("PADIEM_CHAT_SESSION_SECRET"),
            byok_via_b14=os.getenv("BYOK_VIA_B14", "false"),
            custom_key_secret=os.getenv("PADIEM_CHAT_CUSTOM_KEY_SECRET"),
            custom_key_previous_secrets=os.getenv(
                "PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS"
            ),
            custom_key_legacy_session_secrets=os.getenv(
                "PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS"
            ),
            session_max_age_seconds=os.getenv("PADIEM_CHAT_SESSION_MAX_AGE_SECONDS", str(7 * 24 * 3600)),
            cookie_secure=os.getenv("PADIEM_CHAT_COOKIE_SECURE", "true"),
            quota_salt=os.getenv("PADIEM_CHAT_QUOTA_SALT"),
            anonymous_burst_limit=os.getenv("PADIEM_CHAT_ANONYMOUS_BURST_LIMIT", "4"),
            anonymous_daily_limit=os.getenv("PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT", "20"),
            user_burst_limit=os.getenv("PADIEM_CHAT_USER_BURST_LIMIT", "8"),
            user_daily_limit=os.getenv("PADIEM_CHAT_USER_DAILY_LIMIT", "100"),
            global_daily_limit=os.getenv("PADIEM_CHAT_GLOBAL_DAILY_LIMIT", "1000"),
            local_dev=os.getenv("PADIEM_LOCAL_DEV"),
        )
