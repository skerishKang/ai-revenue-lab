#!/usr/bin/env python3
"""Read-only production readiness audit for Padiem Chat public live activation.

This script inspects Cloudflare Worker binding metadata and public health only.
It never mutates Cloudflare, never makes a model/provider request, never prints
secret values, database IDs, account IDs, or full Cloudflare response bodies.

A HOLD result is expected until owner/local provisioning is complete and exits 0
so the current guarded mock deployment remains deployable. Inspection failures
that make the audit itself unreliable exit non-zero.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CF_API = "https://api.cloudflare.com/client/v4"
WORKER_NAME = "padiem-chat"
B14_HEALTH = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/pilot/health"
USER_AGENT = "b62-live-readiness/1.0"

QUOTA_LIMITS = {
    "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT": 1_000_000,
    "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT": 1_000_000,
    "PADIEM_CHAT_USER_BURST_LIMIT": 1_000_000,
    "PADIEM_CHAT_USER_DAILY_LIMIT": 1_000_000,
    "PADIEM_CHAT_GLOBAL_DAILY_LIMIT": 10_000_000,
}
SAFE_TEXT_BINDINGS = frozenset({
    "PADIEM_CHAT_RUNTIME_MODE",
    "PADIEM_CHAT_LIVE_ENABLED",
    "PADIEM_CHAT_B14_BASE_URL",
    *QUOTA_LIMITS.keys(),
})


@dataclass(frozen=True, slots=True)
class Readiness:
    worker_settings_read: bool
    d1_bound: bool
    quota_salt_secret_bound: bool
    finite_limits_configured: bool
    b14_base_bound: bool
    b14_live: bool
    b14_has_key: bool
    runtime_mode: str
    live_switch: str

    @property
    def prerequisites_ready(self) -> bool:
        return all((
            self.worker_settings_read,
            self.d1_bound,
            self.quota_salt_secret_bound,
            self.finite_limits_configured,
            self.b14_base_bound,
            self.b14_live,
            self.b14_has_key,
        ))

    @property
    def public_live_active(self) -> bool:
        return self.prerequisites_ready and self.runtime_mode == "b14" and self.live_switch == "true"

    @property
    def safe_hold(self) -> bool:
        return self.runtime_mode != "b14" or self.live_switch != "true"


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"required GitHub secret/env is missing: {name}")
    return value


def get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(262_144)
            return response.status, json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read(262_144)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {}
        return exc.code, data
    except URLError as exc:
        raise RuntimeError(f"network error while requesting readiness metadata: {exc.reason}") from exc


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("result")
    return value if isinstance(value, dict) else {}


def binding_inventory(payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return binding types and a strict allowlist of non-secret plain-text values.

    Secret binding text is intentionally never copied out of the API payload.
    Unknown plaintext values are also ignored so accidental sensitive plaintext
    cannot be surfaced by this audit.
    """
    result = _result(payload)
    bindings = result.get("bindings")
    if not isinstance(bindings, list):
        return {}, {}

    types: dict[str, str] = {}
    safe_text: dict[str, str] = {}
    for item in bindings:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        kind = item.get("type")
        if not isinstance(name, str) or not isinstance(kind, str):
            continue
        types[name] = kind
        if kind == "plain_text" and name in SAFE_TEXT_BINDINGS:
            text = item.get("text")
            if isinstance(text, str):
                safe_text[name] = text.strip()
    return types, safe_text


def finite_limits_configured(safe_text: dict[str, str]) -> bool:
    for name, maximum in QUOTA_LIMITS.items():
        raw = safe_text.get(name)
        if raw is None:
            return False
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return False
        if not 1 <= value <= maximum:
            return False
    return True


def parse_b14_health(status: int, payload: dict[str, Any]) -> tuple[bool, bool]:
    if status != 200:
        return False, False
    info = payload.get("business14")
    if not isinstance(info, dict):
        return False, False
    return info.get("provider_mode") == "live", info.get("has_key") is True


def evaluate(settings_payload: dict[str, Any], b14_status: int, b14_payload: dict[str, Any]) -> Readiness:
    types, safe_text = binding_inventory(settings_payload)
    b14_live, b14_has_key = parse_b14_health(b14_status, b14_payload)
    return Readiness(
        worker_settings_read=True,
        d1_bound=types.get("PADIEM_CHAT_DB") == "d1",
        quota_salt_secret_bound=types.get("PADIEM_CHAT_QUOTA_SALT") == "secret_text",
        finite_limits_configured=finite_limits_configured(safe_text),
        b14_base_bound=bool(safe_text.get("PADIEM_CHAT_B14_BASE_URL")),
        b14_live=b14_live,
        b14_has_key=b14_has_key,
        runtime_mode=safe_text.get("PADIEM_CHAT_RUNTIME_MODE", "unknown").lower(),
        live_switch=safe_text.get("PADIEM_CHAT_LIVE_ENABLED", "unknown").lower(),
    )


def emit(readiness: Readiness) -> None:
    status = "READY_TO_ARM" if readiness.prerequisites_ready else "HOLD"
    active = "true" if readiness.public_live_active else "false"
    safe_hold = "true" if readiness.safe_hold else "false"
    values = {
        "B62_PUBLIC_LIVE_READINESS": status,
        "WORKER_SETTINGS_READ": readiness.worker_settings_read,
        "QUOTA_STORE_BOUND": readiness.d1_bound,
        "QUOTA_SALT_SECRET_BOUND": readiness.quota_salt_secret_bound,
        "FINITE_QUOTA_LIMITS_CONFIGURED": readiness.finite_limits_configured,
        "B14_BASE_BOUND": readiness.b14_base_bound,
        "B14_PROVIDER_LIVE": readiness.b14_live,
        "B14_HAS_KEY": readiness.b14_has_key,
        "PUBLIC_LIVE_ACTIVE": active,
        "SAFE_HOLD": safe_hold,
    }
    for name, value in values.items():
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        print(f"{name}={rendered}")
    print(f"RUNTIME_MODE={readiness.runtime_mode}")
    print(f"LIVE_SWITCH={readiness.live_switch}")
    print("REAL_PROVIDER_CALLS=0")

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n## B62 public-live read-only readiness\n\n")
            handle.write("| Check | Result |\n|---|---|\n")
            for name, value in values.items():
                rendered = str(value).lower() if isinstance(value, bool) else str(value)
                handle.write(f"| {name} | `{rendered}` |\n")
            handle.write(f"| RUNTIME_MODE | `{readiness.runtime_mode}` |\n")
            handle.write(f"| LIVE_SWITCH | `{readiness.live_switch}` |\n")
            handle.write("| Provider/model calls | `0` |\n")


def main() -> int:
    try:
        token = required_env("CLOUDFLARE_API_TOKEN")
        account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

        settings_status, settings_payload = get_json(
            f"{CF_API}/accounts/{account_id}/workers/scripts/{WORKER_NAME}/settings",
            headers,
        )
        if settings_status == 404:
            readiness = Readiness(False, False, False, False, False, False, False, "absent", "absent")
            emit(readiness)
            return 0
        if settings_status != 200 or settings_payload.get("success") is not True:
            raise RuntimeError(f"Worker settings read failed with HTTP {settings_status}")

        b14_status, b14_payload = get_json(
            B14_HEALTH,
            {"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        readiness = evaluate(settings_payload, b14_status, b14_payload)
        emit(readiness)
        return 0
    except Exception as exc:
        print(f"B62_LIVE_READINESS_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
