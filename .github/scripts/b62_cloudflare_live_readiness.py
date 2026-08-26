#!/usr/bin/env python3
"""Read-only production readiness audit for Padiem Chat public live activation.

This script inspects Cloudflare Worker binding metadata, the bound D1 quota
schema, and public B14 health only. It never mutates Cloudflare, never makes a
model/provider request, never prints secret values, database IDs, account IDs,
or full Cloudflare response bodies.

A HOLD result means the current audit cannot prove every prerequisite. Deployment
state is reported independently so an already-armed Worker is never mislabeled
inactive merely because a read-only prerequisite check is unavailable. Inspection
failures that make the audit itself unreliable exit non-zero.
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
USER_AGENT = "b62-live-readiness/1.3"
B14_SERVICE_BINDING = "B14_SERVICE"

QUOTA_TABLE = "live_usage_buckets"
QUOTA_INDEX = "idx_live_usage_buckets_updated_at"
QUOTA_REQUIRED_COLUMNS = frozenset(
    {
        "subject_type",
        "subject_key",
        "bucket_type",
        "bucket_start",
        "request_count",
        "updated_at",
    }
)

QUOTA_LIMITS = {
    "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT": 1_000_000,
    "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT": 1_000_000,
    "PADIEM_CHAT_USER_BURST_LIMIT": 1_000_000,
    "PADIEM_CHAT_USER_DAILY_LIMIT": 1_000_000,
    "PADIEM_CHAT_GLOBAL_DAILY_LIMIT": 10_000_000,
}
SAFE_TEXT_BINDINGS = frozenset(
    {
        "PADIEM_CHAT_RUNTIME_MODE",
        "PADIEM_CHAT_LIVE_ENABLED",
        "PADIEM_CHAT_B14_BASE_URL",
        *QUOTA_LIMITS.keys(),
    }
)


@dataclass(frozen=True, slots=True)
class Readiness:
    worker_settings_read: bool
    d1_bound: bool
    quota_schema_ready: bool
    quota_schema_status: str
    quota_salt_secret_bound: bool
    finite_limits_configured: bool
    b14_base_bound: bool
    b14_service_bound: bool
    b14_live: bool
    b14_has_key: bool
    runtime_mode: str
    live_switch: str

    @property
    def prerequisites_ready(self) -> bool:
        return all(
            (
                self.worker_settings_read,
                self.d1_bound,
                self.quota_schema_ready,
                self.quota_salt_secret_bound,
                self.finite_limits_configured,
                self.b14_base_bound,
                self.b14_service_bound,
                self.b14_live,
                self.b14_has_key,
            )
        )

    @property
    def public_live_armed(self) -> bool:
        """Report the actual deployment switches, independent of audit proof."""
        return self.runtime_mode == "b14" and self.live_switch == "true"

    @property
    def public_live_active(self) -> bool:
        """Backward-compatible name for the actual deployment armed state."""
        return self.public_live_armed

    @property
    def active_with_unverified_prerequisites(self) -> bool:
        return self.public_live_armed and not self.prerequisites_ready

    @property
    def safe_hold(self) -> bool:
        return not self.public_live_armed


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"required GitHub secret/env is missing: {name}")
    return value


def get_json(
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
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
        raise RuntimeError(
            f"network error while requesting readiness metadata: {exc.reason}"
        ) from exc


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    safe_headers = dict(headers or {})
    safe_headers["Content-Type"] = "application/json"
    request = Request(
        url,
        headers=safe_headers,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
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
        raise RuntimeError("network error while inspecting D1 quota schema") from exc


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("result")
    return value if isinstance(value, dict) else {}


def binding_inventory(
    payload: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return binding types and a strict allowlist of non-secret plain-text values.

    Secret binding text is intentionally never copied out of the API payload.
    Unknown plaintext values are also ignored so accidental sensitive plaintext
    cannot be surfaced by this audit. D1 database identifiers are deliberately
    excluded from both returned mappings.
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


def d1_database_id(payload: dict[str, Any]) -> str | None:
    """Read the known B62 D1 binding identifier for an internal API request only."""
    result = _result(payload)
    bindings = result.get("bindings")
    if not isinstance(bindings, list):
        return None
    for item in bindings:
        if not isinstance(item, dict):
            continue
        if item.get("name") != "PADIEM_CHAT_DB" or item.get("type") != "d1":
            continue
        database_id = item.get("database_id")
        if isinstance(database_id, str) and database_id.strip():
            return database_id.strip()
    return None


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


def parse_b14_health(
    status: int,
    payload: dict[str, Any],
) -> tuple[bool, bool]:
    if status != 200:
        return False, False
    info = payload.get("business14")
    if not isinstance(info, dict):
        return False, False
    return info.get("provider_mode") == "live", info.get("has_key") is True


def evaluate_quota_schema_response(
    status: int,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    """Validate the effective migration-005 schema from a read-only D1 batch query.

    HTTP 401/403 is an expected deployment-permission HOLD. A successful query
    that proves the schema incomplete returns ``missing``. Malformed successful
    responses are audit failures because readiness cannot be evaluated reliably.
    """
    if status in (401, 403):
        return False, "permission_unavailable"
    if status != 200:
        raise RuntimeError("D1 quota schema inspection failed")
    if payload.get("success") is not True:
        raise RuntimeError("D1 quota schema inspection was not successful")

    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 2:
        raise RuntimeError("D1 quota schema inspection returned malformed results")

    objects_result, columns_result = result
    if not isinstance(objects_result, dict) or not isinstance(columns_result, dict):
        raise RuntimeError("D1 quota schema inspection returned malformed query entries")
    if objects_result.get("success") is not True or columns_result.get("success") is not True:
        raise RuntimeError("D1 quota schema inspection query failed")

    object_rows = objects_result.get("results")
    column_rows = columns_result.get("results")
    if not isinstance(object_rows, list) or not isinstance(column_rows, list):
        raise RuntimeError("D1 quota schema inspection rows are malformed")

    objects: set[tuple[str, str]] = set()
    for row in object_rows:
        if not isinstance(row, dict):
            raise RuntimeError("D1 quota schema object row is malformed")
        name = row.get("name")
        kind = row.get("type")
        if isinstance(name, str) and isinstance(kind, str):
            objects.add((kind, name))

    columns: set[str] = set()
    for row in column_rows:
        if not isinstance(row, dict):
            raise RuntimeError("D1 quota schema column row is malformed")
        name = row.get("name")
        if isinstance(name, str):
            columns.add(name)

    ready = (
        ("table", QUOTA_TABLE) in objects
        and ("index", QUOTA_INDEX) in objects
        and QUOTA_REQUIRED_COLUMNS.issubset(columns)
    )
    return ready, "ready" if ready else "missing"


def inspect_quota_schema(
    *,
    account_id: str,
    token: str,
    database_id: str,
) -> tuple[bool, str]:
    """Inspect only schema metadata on the already-bound production D1 database."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    payload = {
        "batch": [
            {
                "sql": (
                    "SELECT type, name FROM sqlite_master "
                    "WHERE name IN (?, ?)"
                ),
                "params": [QUOTA_TABLE, QUOTA_INDEX],
            },
            {"sql": f'PRAGMA table_info("{QUOTA_TABLE}")'},
        ]
    }
    status, response_payload = post_json(
        f"{CF_API}/accounts/{account_id}/d1/database/{database_id}/query",
        payload,
        headers,
    )
    return evaluate_quota_schema_response(status, response_payload)


def evaluate(
    settings_payload: dict[str, Any],
    b14_status: int,
    b14_payload: dict[str, Any],
    *,
    quota_schema_ready: bool = False,
    quota_schema_status: str = "not_checked",
) -> Readiness:
    types, safe_text = binding_inventory(settings_payload)
    b14_live, b14_has_key = parse_b14_health(b14_status, b14_payload)
    return Readiness(
        worker_settings_read=True,
        d1_bound=types.get("PADIEM_CHAT_DB") == "d1",
        quota_schema_ready=quota_schema_ready,
        quota_schema_status=quota_schema_status,
        quota_salt_secret_bound=types.get("PADIEM_CHAT_QUOTA_SALT") == "secret_text",
        finite_limits_configured=finite_limits_configured(safe_text),
        b14_base_bound=bool(safe_text.get("PADIEM_CHAT_B14_BASE_URL")),
        b14_service_bound=types.get(B14_SERVICE_BINDING) == "service",
        b14_live=b14_live,
        b14_has_key=b14_has_key,
        runtime_mode=safe_text.get("PADIEM_CHAT_RUNTIME_MODE", "unknown").lower(),
        live_switch=safe_text.get("PADIEM_CHAT_LIVE_ENABLED", "unknown").lower(),
    )


def emit(readiness: Readiness) -> None:
    status = "READY_TO_ARM" if readiness.prerequisites_ready else "HOLD"
    values = {
        "B62_PUBLIC_LIVE_READINESS": status,
        "WORKER_SETTINGS_READ": readiness.worker_settings_read,
        "QUOTA_STORE_BOUND": readiness.d1_bound,
        "QUOTA_SCHEMA_READY": readiness.quota_schema_ready,
        "D1_SCHEMA_AUDIT": readiness.quota_schema_status,
        "QUOTA_SALT_SECRET_BOUND": readiness.quota_salt_secret_bound,
        "FINITE_QUOTA_LIMITS_CONFIGURED": readiness.finite_limits_configured,
        "B14_BASE_BOUND": readiness.b14_base_bound,
        "B14_SERVICE_BOUND": readiness.b14_service_bound,
        "B14_PROVIDER_LIVE": readiness.b14_live,
        "B14_HAS_KEY": readiness.b14_has_key,
        "PUBLIC_LIVE_ARMED": readiness.public_live_armed,
        "PUBLIC_LIVE_ACTIVE": readiness.public_live_active,
        "ACTIVE_WITH_UNVERIFIED_PREREQUISITES": readiness.active_with_unverified_prerequisites,
        "SAFE_HOLD": readiness.safe_hold,
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
            readiness = Readiness(
                False,
                False,
                False,
                "not_bound",
                False,
                False,
                False,
                False,
                False,
                False,
                "absent",
                "absent",
            )
            emit(readiness)
            return 0
        if settings_status != 200 or settings_payload.get("success") is not True:
            raise RuntimeError(f"Worker settings read failed with HTTP {settings_status}")

        types, _ = binding_inventory(settings_payload)
        database_id = d1_database_id(settings_payload)
        if types.get("PADIEM_CHAT_DB") != "d1":
            quota_schema_ready, quota_schema_status = False, "not_bound"
        elif database_id is None:
            quota_schema_ready, quota_schema_status = False, "binding_id_unavailable"
        else:
            quota_schema_ready, quota_schema_status = inspect_quota_schema(
                account_id=account_id,
                token=token,
                database_id=database_id,
            )

        b14_status, b14_payload = get_json(
            B14_HEALTH,
            {"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        readiness = evaluate(
            settings_payload,
            b14_status,
            b14_payload,
            quota_schema_ready=quota_schema_ready,
            quota_schema_status=quota_schema_status,
        )
        emit(readiness)
        return 0
    except Exception as exc:
        print(f"B62_LIVE_READINESS_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
