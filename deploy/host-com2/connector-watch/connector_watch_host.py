#!/usr/bin/env python3
"""#82 on the host: the things only the executor's own machine can see.

The GitHub-side watch (#6140) reads the lane's status route and Chat's health from
one runner region. Two pieces of the owner's monitoring list are not reachable from
there at all:

* whether the executor **process** is alive, restarted, or exited through the #6099
  watchdog — that is systemd's `ActiveState` and `NRestarts`, and they only exist on
  the host;
* the #6106 `line_blocked_total` / `line_cleared_total` counters — they live in the
  executor's own journal line and are never written to a table.

This script reads those three facts from the host, adds one health read taken from a
**second vantage** (COM2 instead of a GitHub runner), and reports a single verdict
line. It reuses the notification channel the product already configures
(`B66_ALERT_TELEGRAM_*` / `B66_ALERT_DISCORD_WEBHOOK_URL`, the same names the Chat
worker's notifier reads); no new service, no new paid resource, and with none of them
configured it prints and stays quiet instead of pretending to have told anyone.

Dedup: the last state is kept in a small state file and a notification is sent only
when the state word changes. A stuck lane therefore says so once, not every ten
minutes.

Every judgement is a state field: systemd properties, a counter that our own executor
prints as `key=value`, an HTTP status. Nothing is decided by searching a log for a
word, and a counter that cannot be read is `None` — which the verdict reports as
UNKNOWN, never as zero.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

EXECUTOR_UNIT = os.environ.get("CONNECTOR_WATCH_EXECUTOR_UNIT", "padiem-oracle-mesh-executor.service")
CHAT_HEALTH_URL = os.environ.get("CONNECTOR_WATCH_CHAT_HEALTH_URL", "https://chat.padiem.net/health")
STATE_DIR = Path(os.environ.get("CONNECTOR_WATCH_STATE_DIR", "/var/lib/padiem-connector-watch"))
JOURNAL_MINUTES = int(os.environ.get("CONNECTOR_WATCH_JOURNAL_MINUTES", "90"))
REQUEST_TIMEOUT_SECONDS = 20

OK, STALL, UNKNOWN = "ok", "stall", "unknown"
_SEVERITY = {OK: 0, UNKNOWN: 1, STALL: 2}
_COUNTER = re.compile(r"\b(line_blocked_total|line_cleared_total)=(\d{1,9})\b")


def parse_counters(text: str) -> dict[str, int | None]:
    """The last value our own executor printed for each counter, or None.

    The executor prints one structured journal line per completed round
    (`line_blocked_total=N line_cleared_total=M`). These are its own field names, read
    as fields: absence means "not seen", which is reported as None and never as 0.
    """
    latest: dict[str, int | None] = {"line_blocked_total": None, "line_cleared_total": None}
    for match in _COUNTER.finditer(text or ""):
        latest[match.group(1)] = int(match.group(2))
    return latest


def parse_systemd(props: dict[str, Any]) -> dict[str, Any]:
    """`systemctl show` properties, as the fields the verdict reads."""
    active = props.get("ActiveState")
    restarts = props.get("NRestarts")
    exit_status = props.get("ExecMainStatus")
    return {
        "active": active if isinstance(active, str) else None,
        "restarts": restarts if isinstance(restarts, int) and restarts >= 0 else None,
        "exit_status": exit_status if isinstance(exit_status, int) else None,
    }


def process_verdict(props: dict[str, Any]) -> tuple[str, str]:
    """Is the executor process alive?

    Only systemd's own `ActiveState` answers this. `activating`/`deactivating` are not
    called a stop — a restart in progress is normal after the watchdog exits — and an
    unreadable state is UNKNOWN, because "not seen alive" is not "stopped".
    """
    active = props.get("active")
    if active in ("active", "reloading", "activating", "deactivating"):
        return OK, f"executor_{active}"
    if active in ("failed", "inactive"):
        return STALL, f"executor_{active}"
    return UNKNOWN, "executor_state_unreadable"


def restart_verdict(props: dict[str, Any], previous: dict[str, Any] | None) -> tuple[str, str]:
    """Has the executor been restarted since the last run?"""
    restarts = props.get("restarts")
    if restarts is None:
        return UNKNOWN, "restarts_unreadable"
    before = None
    if isinstance(previous, dict):
        before = previous.get("restarts")
    if isinstance(before, bool) or not isinstance(before, int):
        return OK, f"restarts_{restarts}_first_observation"
    if restarts > before:
        # #6099's watchdog exits with 87 when no channel round completed for five
        # minutes. That restart is the lane having stalled; any other restart is a
        # deploy or an operator action, which is a change worth logging and not a stop.
        if props.get("exit_status") == 87:
            return STALL, f"watchdog_restart_{restarts - before}x"
        return OK, f"restarted_{restarts - before}x_not_watchdog"
    return OK, f"restarts_{restarts}"


def counters_verdict(counters: dict[str, int | None]) -> tuple[str, str]:
    """The #6106 counters, reported as numbers whenever they were seen.

    A missing counter is not a stall — the executor may simply not have completed a
    round in the journal window — so it is UNKNOWN, and the caller keeps it in the
    line for the human reading it.
    """
    blocked = counters.get("line_blocked_total")
    cleared = counters.get("line_cleared_total")
    if blocked is None and cleared is None:
        return UNKNOWN, "counters_not_seen"
    # No spaces: this reason rides a single machine-readable line.
    return OK, f"line_blocked={blocked},line_cleared={cleared}"


def health_verdict(status: int | None) -> tuple[str, str]:
    if status == 200:
        return OK, "chat_health_200"
    if isinstance(status, int) and status >= 500:
        return STALL, f"chat_health_{status}"
    return UNKNOWN, f"chat_health_{status if status is not None else 'none'}"


def combine(named: dict[str, tuple[str, str]]) -> tuple[str, list[str]]:
    state = OK
    reasons: list[str] = []
    for name, (verdict, reason) in named.items():
        known = verdict if verdict in _SEVERITY else UNKNOWN
        if _SEVERITY[known] > _SEVERITY[state]:
            state = known
        if known != OK:
            reasons.append(f"{name}={reason}")
    return state, reasons


def should_notify(state: str, previous: Any) -> bool:
    """Only a change of the state word is worth a message."""
    return state != (previous or {}).get("state") if isinstance(previous, dict) else True


# ---- host reads -------------------------------------------------------
def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except Exception:
        return ""
    return done.stdout if done.returncode == 0 else ""


def read_properties(unit: str) -> dict[str, Any]:
    raw = _run(["systemctl", "show", unit,
                "--property=ActiveState,NRestarts,ExecMainStatus", "--no-pager"])
    props: dict[str, Any] = {}
    for line in raw.splitlines():
        key, _, value = line.partition("=")
        if key in ("NRestarts", "ExecMainStatus"):
            try:
                props[key] = int(value.strip())
            except ValueError:
                props[key] = None
        elif key:
            props[key] = value.strip()
    return props


def read_journal(unit: str, minutes: int) -> str:
    return _run(["journalctl", "-u", unit, "--since", f"-{int(minutes)}m",
                 "--no-pager", "-o", "cat"])


def read_health(url: str) -> int | None:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"Accept": "application/json"}),
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def _previous() -> dict[str, Any] | None:
    try:
        return json.loads((STATE_DIR / "last-state.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def _remember(payload: dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "last-state.json").write_text(
            json.dumps(payload), encoding="utf-8",
        )
    except Exception:
        pass


def _notify(text: str) -> str:
    """Reuse the notifier the product already configures. No channel, no new service."""
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
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS):
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
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS):
                sent += 1
        except Exception:
            pass
    return "sent" if sent else "not_configured"


def run(*, unit: str = EXECUTOR_UNIT, journal_minutes: int = JOURNAL_MINUTES,
        health_url: str = CHAT_HEALTH_URL) -> int:
    props = parse_systemd(read_properties(unit))
    previous = _previous()
    counters = parse_counters(read_journal(unit, journal_minutes))
    checks = {
        "process": process_verdict(props),
        "restart": restart_verdict(props, previous),
        "counters": counters_verdict(counters),
        "chat": health_verdict(read_health(health_url)),
    }
    state, reasons = combine(checks)
    print(f"HOST_WATCH={state} unit={unit} reasons={','.join(reasons) if reasons else 'none'}")
    for name in sorted(checks):
        verdict, reason = checks[name]
        print(f"HOST_WATCH_CHECK {name}={verdict} reason={reason}")
    if should_notify(state, previous):
        told = _notify(f"커넥터 감시(COM2): {state} " + (", ".join(reasons) or "all ok"))
        print(f"HOST_WATCH_NOTIFY={told}")
    else:
        print("HOST_WATCH_NOTIFY=suppressed_unchanged")
    _remember({"state": state, "restarts": props.get("restarts")})
    return 1 if state == STALL else 0


def main(argv: list[str] | None = None) -> int:
    del argv
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
