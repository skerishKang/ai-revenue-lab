#!/usr/bin/env python3
"""#4953 — COM2 boot self-check: units, loopback health, tunnel, and an honest alert.

Runs inside WSL after Windows starts it with no user logged in
(padiem-boot-recovery.service, After=multi-user.target). It waits for the units
that must come up, checks each /health and each public tunnel host, records one
JSON report, and — only when something is wrong — sends the same notifier the
connector watch already uses (B66_ALERT_TELEGRAM_* / B66_ALERT_DISCORD_WEBHOOK_URL).

Verdict rules (unit-tested):
* every required service is `enabled` AND `active`; a timer is `enabled` and
  `active (waiting)` — an unreadable state is a failure, never a pass;
* every configured health URL answers 200 with the expected JSON;
* every configured tunnel URL answers through Cloudflare;
* optional entries are reported but cannot fail the boot check.

Nothing here changes any service: no restarts, no writes outside the state dir.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("BOOT_RECOVERY_STATE_DIR", "/var/lib/padiem/boot-recovery"))
CONFIG_PATH = Path(os.environ.get("BOOT_RECOVERY_CONFIG", "/opt/padiem/boot-recovery/units.json"))
DEFAULT_WAIT_SECONDS = 240
DEFAULT_INTERVAL_SECONDS = 5

#: Names come from the installed kit units; MeshCentral/cloudflared are external
#: and may be renamed on the host — units.json overrides them at install time.
DEFAULT_UNITS: list[dict[str, Any]] = [
    {"unit": "padiem-mesh-queue.service", "kind": "service", "required": True},
    {"unit": "padiem-file-lane.service", "kind": "service", "required": True},
    {"unit": "padiem-oracle-mesh-executor.service", "kind": "service", "required": True},
    {"unit": "padiem-connector-watch.service", "kind": "service", "required": True},
    {"unit": "padiem-chat-com2.service", "kind": "service", "required": True},
    {"unit": "padiem-broker.service", "kind": "service", "required": True},
    {"unit": "cloudflared.service", "kind": "service", "required": True},
    {"unit": "meshcentral.service", "kind": "service", "required": True},
    {"unit": "padiem-mesh-queue-backup.timer", "kind": "timer", "required": True},
    {"unit": "padiem-mesh-queue-health.timer", "kind": "timer", "required": True},
    {"unit": "padiem-connector-watch.timer", "kind": "timer", "required": True},
    {"unit": "padiem-chat-com2-backup.timer", "kind": "timer", "required": True},
    {"unit": "padiem-chat-com2-health.timer", "kind": "timer", "required": True},
    {"unit": "padiem-broker-backup.timer", "kind": "timer", "required": True},
    {"unit": "padiem-broker-health.timer", "kind": "timer", "required": True},
    {"unit": "padiem-offsite-backup.timer", "kind": "timer", "required": True},
]
DEFAULT_HEALTH: list[dict[str, Any]] = [
    {"name": "queue", "url": "http://127.0.0.1:8797/health", "expect": "any_ok"},
    {"name": "file-lane", "url": "http://127.0.0.1:8788/health", "expect": "any_ok"},
    {"name": "chat", "url": "http://127.0.0.1:8798/health", "expect": "status_ok"},
    {"name": "broker", "url": "http://127.0.0.1:8799/health", "expect": "status_ok"},
]
DEFAULT_TUNNEL: list[dict[str, Any]] = [
    {"name": "chat-public", "url": "https://chat.padiem.net/health", "expect": "status_ok"},
]

__all__ = [
    "evaluate", "collect_units", "collect_health", "collect_tunnel",
    "load_config", "notify", "run_check", "run_boot",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "units": list(data.get("units") or DEFAULT_UNITS),
            "health": list(data.get("health") or DEFAULT_HEALTH),
            "tunnel": list(data.get("tunnel") or DEFAULT_TUNNEL),
        }
    return {"units": list(DEFAULT_UNITS), "health": list(DEFAULT_HEALTH),
            "tunnel": list(DEFAULT_TUNNEL)}


def evaluate(units: list[dict[str, Any]], health: list[dict[str, Any]],
             tunnel: list[dict[str, Any]]) -> dict[str, Any]:
    """The whole verdict, pure: PASS only when every required check passed."""

    failures: list[str] = []
    skipped: list[str] = []
    for entry in units:
        unit = str(entry.get("unit"))
        required = bool(entry.get("required", True))
        enabled = entry.get("enabled")
        active = entry.get("active")
        ok = enabled is True and active is True
        if ok:
            continue
        reason = "enabled=%s active=%s" % (
            "true" if enabled is True else ("false" if enabled is False else "unknown"),
            "true" if active is True else ("false" if active is False else "unknown"),
        )
        if required:
            failures.append(f"unit:{unit}({reason})")
        else:
            skipped.append(f"unit:{unit}({reason})")
    for item in health:
        if item.get("ok") is not True:
            line = f"health:{item.get('name')}({item.get('detail') or 'failed'})"
            if item.get("required", True):
                failures.append(line)
            else:
                skipped.append(line)
    for item in tunnel:
        if item.get("ok") is not True:
            line = f"tunnel:{item.get('name')}({item.get('detail') or 'failed'})"
            if item.get("required", True):
                failures.append(line)
            else:
                skipped.append(line)
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "skipped": skipped,
        "checked_at": _now(),
    }


def _systemctl(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["systemctl", *args], capture_output=True, text=True, timeout=20,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 255, "systemctl_unavailable"


def collect_units(config: dict[str, Any]) -> list[dict[str, Any]]:
    states = []
    for entry in config["units"]:
        unit = str(entry["unit"])
        enabled_code, _ = _systemctl("is-enabled", unit)
        active_code, _ = _systemctl("is-active", unit)
        states.append({
            "unit": unit,
            "kind": entry.get("kind", "service"),
            "required": bool(entry.get("required", True)),
            "enabled": True if enabled_code == 0 else (False if enabled_code in (1, 3) else None),
            "active": True if active_code == 0 else (False if active_code == 3 else None),
        })
    return states


def _json_ok(payload: Any, expect: str) -> bool:
    if not isinstance(payload, dict):
        return False
    if expect == "status_ok":
        return payload.get("status") == "ok"
    return payload.get("status") == "ok" or payload.get("ok") is True


def _read_json(url: str, timeout: float = 5.0) -> tuple[bool, str, Any]:
    try:
        # A named user agent: the padiem.net Cloudflare zone's managed rules
        # answer 403 to the default Python-urllib UA, which would make every
        # public tunnel probe a false boot failure.
        request = urllib.request.Request(url, headers={"user-agent": "padiem-boot-recovery/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False, f"http_{response.status}", None
            raw = response.read(65537)
        return True, "ok", json.loads(raw)
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}", None
    except Exception:
        return False, "unreachable", None


def collect_health(config: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for entry in config["health"]:
        ok, detail, payload = _read_json(str(entry["url"]))
        results.append({
            "name": entry.get("name", entry["url"]),
            "required": bool(entry.get("required", True)),
            "ok": bool(ok and _json_ok(payload, str(entry.get("expect", "any_ok")))),
            "detail": detail,
        })
    return results


def collect_tunnel(config: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for entry in config["tunnel"]:
        ok, detail, payload = _read_json(str(entry["url"]), timeout=10.0)
        results.append({
            "name": entry.get("name", entry["url"]),
            "required": bool(entry.get("required", True)),
            "ok": bool(ok and _json_ok(payload, str(entry.get("expect", "status_ok")))),
            "detail": detail,
        })
    return results


def notify(text: str) -> str:
    """Same notifier names the connector watch uses; silent failure, honest word."""

    token = os.environ.get("B66_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("B66_ALERT_TELEGRAM_CHAT_ID", "").strip()
    hook = os.environ.get("B66_ALERT_DISCORD_WEBHOOK_URL", "").strip()
    sent = 0
    if token and chat_id:
        try:
            body = json.dumps({"chat_id": chat_id, "text": text[:3500]}).encode("utf-8")
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                method="POST", headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10):
                sent += 1
        except Exception:
            pass
    if hook:
        try:
            body = json.dumps({"content": text[:1900]}).encode("utf-8")
            request = urllib.request.Request(
                hook, data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10):
                sent += 1
        except Exception:
            pass
    return "sent" if sent else "not_configured"


def _write_state(report: dict[str, Any]) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / "last.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def run_check(*, wait_seconds: int = 0, interval: int = DEFAULT_INTERVAL_SECONDS) -> int:
    config = load_config()
    deadline = time.monotonic() + max(0, wait_seconds)
    while True:
        units = collect_units(config)
        pending = [u for u in units if u["required"] and not (u["enabled"] and u["active"])]
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(interval)
    health = collect_health(config)
    tunnel = collect_tunnel(config)
    report = evaluate(units, health, tunnel)
    report.update({
        "waited_seconds": max(0, wait_seconds),
        "units": units,
        "health": health,
        "tunnel": tunnel,
    })
    path = _write_state(report)
    print(f"BOOT_RECOVERY={report['status']} failures={len(report['failures'])} state={path}")
    for line in report["failures"]:
        print(f"BOOT_RECOVERY_FAIL {line}")
    for line in report["skipped"]:
        print(f"BOOT_RECOVERY_SKIP {line}")
    if report["status"] != "PASS":
        told = notify(
            "COM2 부팅 점검 실패: " + (", ".join(report["failures"][:8]) or "unknown")
        )
        print(f"BOOT_RECOVERY_NOTIFY={told}")
    return 0 if report["status"] == "PASS" else 1


def run_boot(wait_seconds: int = DEFAULT_WAIT_SECONDS) -> int:
    _systemctl("is-system-running", "--wait")
    return run_check(wait_seconds=wait_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--wait-seconds", type=int, default=0)
    boot = sub.add_parser("boot")
    boot.add_argument("--wait-seconds", type=int, default=DEFAULT_WAIT_SECONDS)
    args = parser.parse_args(argv)
    if args.command == "boot":
        return run_boot(args.wait_seconds)
    return run_check(wait_seconds=args.wait_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
