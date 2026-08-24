from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlsplit, urlunsplit


class ConfigError(ValueError):
    pass


def _normalize_base_url(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError("PADIEM_CHAT_B14_BASE_URL must use http or https")
    if not parsed.hostname:
        raise ConfigError("PADIEM_CHAT_B14_BASE_URL must include a host")
    if parsed.username or parsed.password:
        raise ConfigError("PADIEM_CHAT_B14_BASE_URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise ConfigError("PADIEM_CHAT_B14_BASE_URL must not include query or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


@dataclass(frozen=True)
class Settings:
    runtime_mode: str = "mock"
    b14_base_url: str | None = None
    timeout_seconds: float = 20.0

    @classmethod
    def from_values(
        cls,
        runtime_mode: object = "mock",
        b14_base_url: object = None,
        timeout_seconds: object = 20.0,
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

        return cls(runtime_mode=mode, b14_base_url=base, timeout_seconds=timeout)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls.from_values(
            runtime_mode=os.getenv("PADIEM_CHAT_RUNTIME_MODE", "mock"),
            b14_base_url=os.getenv("PADIEM_CHAT_B14_BASE_URL"),
            timeout_seconds=os.getenv("PADIEM_CHAT_TIMEOUT_SECONDS", "20"),
        )
