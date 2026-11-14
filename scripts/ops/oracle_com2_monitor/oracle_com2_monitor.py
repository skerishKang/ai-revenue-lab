#!/usr/bin/env python3
"""Monitor COM2 liveness and public endpoints from the Oracle standby host.

The monitor is deliberately small and dependency-free.  It reads the COM2
heartbeat file that the existing failover receiver writes, probes the public
Chat status and Mesh access URLs, and sends one alert when a run of failures
crosses the configured threshold.  Recovery is also reported once.  While the
fault persists no further alert is sent.

Telegram credentials are read from ``TELEGRAM_BOT_TOKEN`` and
``TELEGRAM_CHAT_ID`` in the process environment.  The repository and systemd
unit contain only those names; values belong in the private Oracle environment
file.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from typing import Any, Callable
from urllib import error, request


SCHEMA = "padiem_com2_monitor/v1"
STATUS_HEALTHY = "healthy"
STATUS_PENDING = "pending"
STATUS_FAULT = "fault"
ALERT_FAULT = "FAULT"
ALERT_RECOVERY = "RECOVERY"
DEFAULT_FAILURE_THRESHOLD = 2
DEFAULT_HEARTBEAT_STALE_SECONDS = 180
DEFAULT_TIMEOUT_SECONDS = 10


class MonitorError(Exception):
    """A bounded monitor error that is safe to print."""


class NotifyError(MonitorError):
    """A Telegram delivery failure without token, chat, or response detail."""


@dataclass(frozen=True)
class Observation:
    """One bounded observation.  No credential or response body is stored."""

    now: float
    heartbeat_age_seconds: float | None
    chat_status: int | None
    mesh_status: int | None

    def failures(self, heartbeat_stale_seconds: int) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.heartbeat_age_seconds is None:
            reasons.append("heartbeat_missing")
        elif self.heartbeat_age_seconds > heartbeat_stale_seconds:
            reasons.append("heartbeat_stale")
        if self.chat_status is None:
            reasons.append("chat_unreachable")
        elif not 200 <= self.chat_status < 300:
            reasons.append(f"chat_http_{self.chat_status}")
        if self.mesh_status is None:
            reasons.append("mesh_unreachable")
        elif not 200 <= self.mesh_status < 300:
            reasons.append(f"mesh_http_{self.mesh_status}")
        return tuple(reasons)


@dataclass(frozen=True)
class Config:
    heartbeat_path: str
    state_path: str
    chat_status_url: str
    mesh_status_url: str
    heartbeat_stale_seconds: int = DEFAULT_HEARTBEAT_STALE_SECONDS
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


def _required_text(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise MonitorError(f"config_{name}_missing")
    return value.strip()


def _positive_int(data: dict[str, Any], name: str, default: int) -> int:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MonitorError(f"config_{name}_invalid")
    return value


def load_config(path: str | Path) -> Config:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise MonitorError("config_unreadable") from exc
    if not isinstance(data, dict):
        raise MonitorError("config_not_object")
    heartbeat_path = _required_text(data, "heartbeat_path")
    state_path = _required_text(data, "state_path")
    chat_status_url = _required_text(data, "chat_status_url")
    mesh_status_url = _required_text(data, "mesh_status_url")
    for name, value in (
        ("chat_status_url", chat_status_url),
        ("mesh_status_url", mesh_status_url),
    ):
        if not value.startswith(("https://", "http://")):
            raise MonitorError(f"config_{name}_invalid")
    threshold = _positive_int(data, "failure_threshold", DEFAULT_FAILURE_THRESHOLD)
    if threshold < 2:
        raise MonitorError("config_failure_threshold_too_low")
    return Config(
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        chat_status_url=chat_status_url,
        mesh_status_url=mesh_status_url,
        heartbeat_stale_seconds=_positive_int(
            data, "heartbeat_stale_seconds", DEFAULT_HEARTBEAT_STALE_SECONDS
        ),
        failure_threshold=threshold,
        timeout_seconds=_positive_int(
            data, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS
        ),
    )


def heartbeat_age_seconds(path: str | Path, now: float | None = None) -> float | None:
    """Return the heartbeat file age, or None when the signal is absent.

    The receiver replaces the file atomically, so the mtime is the last receipt
    time.  A small clock skew into the future is clamped to zero; the monitor
    does not invent a stale signal from that condition.
    """
    try:
        modified = os.stat(path).st_mtime
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return None
    current = time.time() if now is None else now
    return max(0.0, float(current) - float(modified))


def probe_http(url: str, timeout_seconds: int) -> int | None:
    """Return the final HTTP status code, or None for a transport failure."""
    req = request.Request(
        url,
        headers={"User-Agent": "padiem-com2-monitor/1.0", "Accept": "*/*"},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            return int(response.status)
    except error.HTTPError as exc:
        return int(exc.code)
    except (error.URLError, TimeoutError, OSError, ValueError):
        return None


def collect_observation(
    config: Config,
    *,
    now: float | None = None,
    age_reader: Callable[[str | Path, float | None], float | None] = heartbeat_age_seconds,
    http_probe: Callable[[str, int], int | None] = probe_http,
) -> Observation:
    current = time.time() if now is None else float(now)
    return Observation(
        now=current,
        heartbeat_age_seconds=age_reader(config.heartbeat_path, current),
        chat_status=http_probe(config.chat_status_url, config.timeout_seconds),
        mesh_status=http_probe(config.mesh_status_url, config.timeout_seconds),
    )


def _default_state(now: float) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": STATUS_HEALTHY,
        "consecutive_failures": 0,
        "failure_since": None,
        "last_check": now,
        "last_heartbeat_age_seconds": None,
        "last_chat_status": None,
        "last_mesh_status": None,
        "last_alert_at": None,
        "last_alert_kind": None,
        "last_error": "",
    }


def load_state(path: str | Path, now: float | None = None) -> dict[str, Any]:
    current = time.time() if now is None else float(now)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_state(current)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return _default_state(current)
    if data.get("status") not in (STATUS_HEALTHY, STATUS_PENDING, STATUS_FAULT):
        return _default_state(current)
    return data


def write_state(path: str | Path, state: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o640)
    except OSError:
        pass
    os.replace(temporary, target)


def evaluate(
    previous: dict[str, Any] | None,
    observation: Observation,
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    heartbeat_stale_seconds: int = DEFAULT_HEARTBEAT_STALE_SECONDS,
) -> tuple[dict[str, Any], str | None]:
    """Return the next persisted state and one optional alert kind.

    The threshold is a count of consecutive failed observations.  A single
    failed observation stays pending and silent.  A fault already in the fault
    state never re-alerts.  The first healthy observation after a fault emits
    exactly one recovery alert.
    """
    if failure_threshold < 2:
        raise MonitorError("failure_threshold_too_low")
    state = dict(previous or _default_state(observation.now))
    status = state.get("status")
    if status not in (STATUS_HEALTHY, STATUS_PENDING, STATUS_FAULT):
        status = STATUS_HEALTHY
    count = state.get("consecutive_failures", 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        count = 0

    failures = observation.failures(heartbeat_stale_seconds)
    alert: str | None = None
    if failures:
        count += 1
        failure_since = state.get("failure_since")
        if not isinstance(failure_since, (int, float)):
            failure_since = observation.now
        if status == STATUS_FAULT:
            next_status = STATUS_FAULT
        elif count >= failure_threshold:
            next_status = STATUS_FAULT
            alert = ALERT_FAULT
        else:
            next_status = STATUS_PENDING
    else:
        count = 0
        failure_since = None
        if status == STATUS_FAULT:
            next_status = STATUS_HEALTHY
            alert = ALERT_RECOVERY
        else:
            next_status = STATUS_HEALTHY

    state.update(
        {
            "schema": SCHEMA,
            "status": next_status,
            "consecutive_failures": count,
            "failure_since": failure_since,
            "last_check": observation.now,
            "last_heartbeat_age_seconds": observation.heartbeat_age_seconds,
            "last_chat_status": observation.chat_status,
            "last_mesh_status": observation.mesh_status,
            "last_error": ",".join(failures),
        }
    )
    return state, alert


def _http_label(status: int | None) -> str:
    return "응답 없음" if status is None else f"HTTP {status}"


def _age_label(age: float | None) -> str:
    return "없음" if age is None else f"{age:.0f}초 전"


def format_alert(
    kind: str,
    state: dict[str, Any],
    observation: Observation,
    *,
    failure_threshold: int,
) -> str:
    stamp = datetime.fromtimestamp(observation.now, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    if kind == ALERT_FAULT:
        heading = "[PADIEM COM2] 장애 감지"
        detail = f"- 연속 실패: {state.get('consecutive_failures', 0)}회 (기준 {failure_threshold}회)"
    elif kind == ALERT_RECOVERY:
        heading = "[PADIEM COM2] 회복"
        detail = "- 연속 실패: 0회"
    else:
        raise MonitorError("unknown_alert_kind")
    return "\n".join(
        (
            heading,
            detail,
            f"- 컴2 생존 신호: {_age_label(observation.heartbeat_age_seconds)}",
            f"- Chat 상태: {_http_label(observation.chat_status)}",
            f"- 메시 접속: {_http_label(observation.mesh_status)}",
            f"- 확인 시각: {stamp}",
        )
    )


class TelegramNotifier:
    """Minimal Bot API sender that never includes credentials in errors."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        timeout_seconds: int = 20,
        opener: Callable[..., Any] = request.urlopen,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def __call__(self, text: str) -> None:
        if len(text) > 4096:
            raise NotifyError("telegram_message_too_large")
        payload = json.dumps(
            {"chat_id": self._chat_id, "text": text}, ensure_ascii=False
        ).encode("utf-8")
        req = request.Request(
            "https://api.telegram.org/bot" + self._token + "/sendMessage",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "padiem-com2-monitor/1.0",
            },
            method="POST",
        )
        try:
            with self._opener(req, timeout=self._timeout_seconds) as response:
                status = int(response.status)
                data = json.loads(response.read(65537))
        except error.HTTPError as exc:
            raise NotifyError(f"telegram_http_{exc.code}") from None
        except (error.URLError, TimeoutError, OSError, ValueError):
            raise NotifyError("telegram_network_error") from None
        if status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            raise NotifyError("telegram_rejected")


def notifier_from_environment(
    environ: dict[str, str],
) -> TelegramNotifier | None:
    token = environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return TelegramNotifier(token, chat_id)


def run_once(
    config_path: str | Path,
    *,
    environ: dict[str, str] | None = None,
    now: float | None = None,
    observer: Callable[[Config, float], Observation] | None = None,
    notifier: Callable[[str], None] | None = None,
) -> int:
    """Observe once, persist the decision, and return a bounded exit code."""
    config = load_config(config_path)
    current = time.time() if now is None else float(now)
    previous = load_state(config.state_path, current)
    if observer is None:
        observation = collect_observation(config, now=current)
    else:
        observation = observer(config, current)
    state, alert = evaluate(
        previous,
        observation,
        failure_threshold=config.failure_threshold,
        heartbeat_stale_seconds=config.heartbeat_stale_seconds,
    )
    if alert is None:
        write_state(config.state_path, state)
        return 0

    message = format_alert(
        alert,
        state,
        observation,
        failure_threshold=config.failure_threshold,
    )
    sender = notifier if notifier is not None else notifier_from_environment(
        dict(os.environ if environ is None else environ)
    )
    if sender is None:
        print("MONITOR_NOTIFY_UNAVAILABLE=TELEGRAM_NOT_CONFIGURED")
        return 1
    try:
        sender(message)
    except NotifyError as exc:
        print(f"MONITOR_NOTIFY_FAILED={exc}")
        return 1
    except Exception:
        print("MONITOR_NOTIFY_FAILED=UNEXPECTED")
        return 1
    state["last_alert_at"] = observation.now
    state["last_alert_kind"] = alert
    write_state(config.state_path, state)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PADIEM Oracle COM2 monitor")
    parser.add_argument("--config", required=True, help="path to monitor JSON")
    args = parser.parse_args(argv)
    try:
        return run_once(args.config)
    except MonitorError as exc:
        print(f"MONITOR_FAILED={exc}")
        return 1
    except Exception:
        print("MONITOR_FAILED=UNEXPECTED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
