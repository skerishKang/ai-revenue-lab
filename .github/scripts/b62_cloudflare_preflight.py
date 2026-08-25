#!/usr/bin/env python3
"""Read-only Cloudflare/B14 preflight for Padiem Chat deployment.

Prints and records only safe state. It never prints token values or full
Cloudflare response bodies and it makes no provider/model request.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CF_API = "https://api.cloudflare.com/client/v4"
B14_HEALTH = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/pilot/health"
WORKER_NAME = "padiem-chat"
USER_AGENT = "b62-preflight/1.0"


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"required GitHub secret/env is missing: {name}")
    return value


def cf_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


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
        raise RuntimeError(f"network error while requesting {url}: {exc.reason}") from exc


def get_status_without_body(url: str, headers: dict[str, str]) -> int:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except URLError as exc:
        raise RuntimeError(f"network error while requesting Workers API: {exc.reason}") from exc


def write_output(name: str, value: str) -> None:
    target = os.getenv("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def append_summary(lines: list[str]) -> None:
    target = os.getenv("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def read_b14_health() -> dict[str, str]:
    state = {
        "b14_http": "0",
        "b14_status": "unavailable",
        "b14_provider_mode": "unknown",
        "b14_has_key": "unknown",
        "b14_catalog_models": "unknown",
    }
    try:
        status, payload = get_json(
            B14_HEALTH,
            {"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        state["b14_http"] = str(status)
        if status == 200:
            state["b14_status"] = str(payload.get("status", "unknown"))
            info = payload.get("business14") if isinstance(payload.get("business14"), dict) else {}
            state["b14_provider_mode"] = str(info.get("provider_mode", "unknown"))
            key_value = info.get("has_key")
            if isinstance(key_value, bool):
                state["b14_has_key"] = "true" if key_value else "false"
            state["b14_catalog_models"] = str(info.get("catalog_models", "unknown"))
    except Exception:
        pass
    return state


def emit_b14(state: dict[str, str]) -> None:
    for key, value in state.items():
        write_output(key, value)
    print(f"B14_HEALTH_HTTP={state['b14_http']}")
    print(f"B14_STATUS={state['b14_status']}")
    print(f"B14_PROVIDER_MODE={state['b14_provider_mode']}")
    print(f"B14_HAS_KEY={state['b14_has_key']}")
    print(f"B14_CATALOG_MODELS={state['b14_catalog_models']}")
    print("REAL_PROVIDER_CALLS=0")


def main() -> int:
    b14 = read_b14_health()
    emit_b14(b14)

    try:
        token = required_env("CLOUDFLARE_API_TOKEN")
        account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
        headers = cf_headers(token)

        verify_status, verify = get_json(f"{CF_API}/user/tokens/verify", headers)
        if verify_status != 200 or verify.get("success") is not True:
            raise RuntimeError(f"Cloudflare token verification failed with HTTP {verify_status}")

        worker_status = get_status_without_body(
            f"{CF_API}/accounts/{account_id}/workers/scripts/{WORKER_NAME}", headers
        )
        if worker_status == 200:
            worker_state = "existing"
        elif worker_status == 404:
            worker_state = "absent"
        elif worker_status in {401, 403}:
            worker_state = "permission_denied"
            write_output("worker_state", worker_state)
            append_summary([
                "## B62 Cloudflare read-only preflight",
                "",
                "| Check | Result |",
                "|---|---|",
                "| Cloudflare token verify | PASS |",
                f"| Workers script read | `HTTP {worker_status} — permission denied` |",
                f"| B14 health HTTP | `{b14['b14_http']}` |",
                f"| B14 status | `{b14['b14_status']}` |",
                f"| B14 provider mode | `{b14['b14_provider_mode']}` |",
                f"| B14 has server key | `{b14['b14_has_key']}` |",
                f"| B14 catalog models | `{b14['b14_catalog_models']}` |",
                "| Provider/model calls | `0` |",
            ])
            raise RuntimeError(
                f"Cloudflare token lacks Workers script read permission (HTTP {worker_status})"
            )
        else:
            raise RuntimeError(f"unexpected Workers script lookup HTTP {worker_status}")

        subdomain_status, subdomain_payload = get_json(
            f"{CF_API}/accounts/{account_id}/workers/subdomain", headers
        )
        if subdomain_status != 200 or subdomain_payload.get("success") is not True:
            raise RuntimeError(f"workers.dev subdomain lookup failed with HTTP {subdomain_status}")
        subdomain = str((subdomain_payload.get("result") or {}).get("subdomain") or "").strip()
        if not subdomain:
            raise RuntimeError("workers.dev subdomain is empty")

        write_output("worker_state", worker_state)
        write_output("subdomain", subdomain)

        print("CLOUDFLARE_TOKEN_VERIFY=PASS")
        print(f"PADIEM_CHAT_WORKER_STATE={worker_state}")
        print(f"WORKERS_DEV_SUBDOMAIN={subdomain}")

        append_summary([
            "## B62 Cloudflare read-only preflight",
            "",
            "| Check | Result |",
            "|---|---|",
            "| Cloudflare token verify | PASS |",
            f"| `padiem-chat` Worker | `{worker_state}` |",
            f"| workers.dev subdomain | `{subdomain}` |",
            f"| B14 health HTTP | `{b14['b14_http']}` |",
            f"| B14 status | `{b14['b14_status']}` |",
            f"| B14 provider mode | `{b14['b14_provider_mode']}` |",
            f"| B14 has server key | `{b14['b14_has_key']}` |",
            f"| B14 catalog models | `{b14['b14_catalog_models']}` |",
            "| Provider/model calls | `0` |",
        ])
        return 0
    except Exception as exc:
        print(f"B62_PREFLIGHT_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
