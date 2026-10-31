#!/usr/bin/env python3
"""Read-only post-cutover observation report for the COM2 Chat host.

The report answers one question for issues #5479 and #6127: after the
2026-10-31 cutover, did the moved services keep answering without the Python
Worker ``NoGilError`` signature or 5xx responses on the two named endpoints?

Inputs are journald windows for ``padiem-chat-com2``, ``padiem-p01`` and
``padiem-b14``. The script reads journals with ``journalctl`` and systemd
properties with ``systemctl show``. It never starts, stops, restarts, enables,
reloads or reconfigures a unit and never changes a log setting.

Journal messages are never printed. Health responses are read up to 64 KiB
only to check ``status == "ok"`` and are never printed. The report contains
counts, normalized route labels, unit state, restart counts and health results
only. It does not contain request bodies, query strings, headers, cookies,
client addresses, user or conversation identifiers, request ids or secret
values.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KIND = "PADIEM_COM2_POST_CUTOVER_REPORT_V1"
DEFAULT_CUTOVER = "2026-10-31T21:07:00+09:00"
DEFAULT_WINDOW = timedelta(hours=24)
CLOSURE_WINDOW = timedelta(hours=24)
UNITS = ("padiem-chat-com2", "padiem-p01", "padiem-b14")
CHAT_UNIT = "padiem-chat-com2"
DEFAULT_HEALTH_URLS = {
    "padiem-chat-com2": "http://127.0.0.1:8798/health",
    "padiem-p01": "http://127.0.0.1:8811/internal/v1/health",
    "padiem-b14": "http://127.0.0.1:8789/health",
}
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
SAFE_ROUTES = frozenset(
    {
        "/health",
        "/internal/v1/health",
        "/api/auth/status",
        "/api/projects",
    }
)
DYNAMIC_PREFIXES = (
    "/api/projects/",
    "/api/conversations/",
    "/api/documents/",
    "/api/saved-outputs/",
    "/api/files/",
    "/api/claw/",
    "/internal/",
)
FOCUS_ROUTES = ("/api/auth/status", "/api/projects")
TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):")
ERROR_RE = re.compile(r"\bERROR\b")
ACCESS_RE = re.compile(
    r'"\s*(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+HTTP/\d(?:\.\d)?\s*"\s+(?P<status>\d{3})(?:\s|$)'
)
SEGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._~-]{0,31}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def parse_moment(value: str) -> datetime:
    """Parse an ISO-8601 moment. A naive value is read in the host timezone."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return moment


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def resolve_window(since: str | None, until: str | None, now: datetime) -> tuple[datetime, datetime]:
    end = parse_moment(until) if until else now
    start = parse_moment(since) if since else end - DEFAULT_WINDOW
    if start >= end:
        raise ValueError("since must be earlier than until")
    return start, end


def journalctl_argv(unit: str, start: datetime, end: datetime, binary: str = "journalctl") -> list[str]:
    return [
        binary,
        "--unit",
        unit,
        "--since",
        "@%d" % int(start.timestamp()),
        "--until",
        "@%d" % int(end.timestamp()),
        "--no-pager",
        "--quiet",
        "--output",
        "cat",
    ]


def systemctl_argv(unit: str, binary: str = "systemctl") -> list[str]:
    return [
        binary,
        "show",
        unit,
        "--property=ActiveState,NRestarts,ExecMainStatus",
        "--no-pager",
    ]


def read_command(argv: Sequence[str], timeout: float) -> tuple[str | None, str | None]:
    try:
        done = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as exc:
        return None, type(exc).__name__
    if done.returncode != 0:
        return None, "exit_%d" % done.returncode
    return done.stdout, None


def parse_systemd_props(text: str) -> dict[str, Any]:
    props: dict[str, Any] = {
        "active_state": None,
        "n_restarts": None,
        "exec_main_status": None,
    }
    for line in (text or "").splitlines():
        key, separator, raw = line.partition("=")
        if not separator:
            continue
        value = raw.strip()
        if key == "ActiveState":
            props["active_state"] = value or None
        elif key in ("NRestarts", "ExecMainStatus"):
            try:
                props["n_restarts" if key == "NRestarts" else "exec_main_status"] = int(value)
            except ValueError:
                props["n_restarts" if key == "NRestarts" else "exec_main_status"] = None
    return props


def normalize_route(raw: Any) -> str:
    """Reduce a request target to a bounded, non-identifying route label."""
    if not isinstance(raw, str):
        return "<unknown>"
    path = raw.split("?", 1)[0].split("#", 1)[0].strip()
    if not path.startswith("/"):
        return "<unknown>"
    if path in SAFE_ROUTES:
        return path
    for prefix in DYNAMIC_PREFIXES:
        if path.startswith(prefix):
            return prefix.rstrip("/") + "/*"
    segments = [part for part in path.split("/") if part]
    if not segments:
        return "/"
    labels: list[str] = []
    for segment in segments[:2]:
        if SEGMENT_RE.fullmatch(segment):
            labels.append(segment)
        else:
            labels.append("*")
            break
    route = "/" + "/".join(labels)
    if len(segments) > 2 and not route.endswith("/*"):
        route += "/*"
    return route


def parse_request_event(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("event") != "http_request":
        return None
    status = payload.get("status")
    if isinstance(status, bool) or not isinstance(status, int):
        return None
    return payload


def analyze_journal(text: str) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "tracebacks": 0,
        "error_lines": 0,
        "nogil_occurrences": 0,
        "pyproxy_occurrences": 0,
        "telemetry_records": 0,
        "access_records": 0,
        "telemetry_5xx": {},
        "access_5xx": {},
    }
    for line in (text or "").splitlines():
        if TRACEBACK_RE.match(line):
            stats["tracebacks"] += 1
        if ERROR_RE.search(line):
            stats["error_lines"] += 1
        stats["nogil_occurrences"] += line.count("NoGilError")
        stats["pyproxy_occurrences"] += line.count("PyProxy")
        event = parse_request_event(line)
        if event is not None:
            stats["telemetry_records"] += 1
            if 500 <= event["status"] <= 599:
                route = normalize_route(event.get("route"))
                bucket = stats["telemetry_5xx"]
                bucket[route] = bucket.get(route, 0) + 1
            continue
        match = ACCESS_RE.search(line)
        if match is not None:
            stats["access_records"] += 1
            if 500 <= int(match.group("status")) <= 599:
                route = normalize_route(match.group("path"))
                bucket = stats["access_5xx"]
                bucket[route] = bucket.get(route, 0) + 1
    return stats


def sorted_routes(counts: Mapping[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def focus_counts(by_route: Mapping[str, int]) -> dict[str, int]:
    result = {name: 0 for name in FOCUS_ROUTES}
    for route, count in by_route.items():
        if route == "/api/auth/status":
            result["/api/auth/status"] += count
        elif route == "/api/projects" or route.startswith("/api/projects/"):
            result["/api/projects"] += count
    return result


def unavailable_http(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "source": None,
        "request_records": 0,
        "total": None,
        "by_route": {},
        "focus": {name: None for name in FOCUS_ROUTES},
        "reason": reason,
    }


def choose_http(stats: Mapping[str, Any]) -> dict[str, Any]:
    if stats["telemetry_records"]:
        by_route = sorted_routes(stats["telemetry_5xx"])
        return {
            "available": True,
            "source": "app_request_events",
            "request_records": stats["telemetry_records"],
            "total": sum(by_route.values()),
            "by_route": by_route,
            "focus": focus_counts(by_route),
        }
    if stats["access_records"]:
        by_route = sorted_routes(stats["access_5xx"])
        return {
            "available": True,
            "source": "access_log",
            "request_records": stats["access_records"],
            "total": sum(by_route.values()),
            "by_route": by_route,
            "focus": focus_counts(by_route),
        }
    return unavailable_http("no_request_records")


def probe_health(url: str, timeout: float) -> dict[str, Any]:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return {"status": "INVALID", "http_status": None, "reason": "url_unparseable"}
    if (
        parsed.scheme != "http"
        or parsed.hostname not in LOOPBACK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return {"status": "INVALID", "http_status": None, "reason": "url_not_loopback"}
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read(65_537)
    except urllib.error.HTTPError as exc:
        return {"status": "FAIL", "http_status": int(exc.code), "reason": "http_status"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "UNREACHABLE", "http_status": None, "reason": type(exc).__name__}
    if status != 200:
        return {"status": "FAIL", "http_status": status, "reason": "http_status"}
    if len(raw) > 65_536:
        return {"status": "FAIL", "http_status": status, "reason": "health_body_too_large"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"status": "FAIL", "http_status": status, "reason": "health_body_malformed"}
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return {"status": "FAIL", "http_status": status, "reason": "status_not_ok"}
    return {"status": "PASS", "http_status": status}


def observe_unit(
    unit: str,
    journal_text: str | None,
    journal_error: str | None,
    props_text: str | None,
    health: Mapping[str, Any] | None,
) -> dict[str, Any]:
    props = parse_systemd_props(props_text or "")
    stats = analyze_journal(journal_text or "")
    if journal_error is not None:
        counts = None
        http = unavailable_http("journal_unreadable")
        lines = 0
    else:
        counts = {
            "tracebacks": stats["tracebacks"],
            "error_lines": stats["error_lines"],
            "nogil_occurrences": stats["nogil_occurrences"],
            "pyproxy_occurrences": stats["pyproxy_occurrences"],
        }
        http = choose_http(stats)
        lines = len((journal_text or "").splitlines())
    return {
        "unit": unit,
        "journal": {
            "read": journal_error is None,
            "error": journal_error,
            "lines": lines,
        },
        "systemd": props,
        "counts": counts,
        "http_5xx": http,
        "health": dict(health) if health is not None else {"status": "SKIPPED", "http_status": None},
    }


def get_unit(units: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any] | None:
    for unit in units:
        if unit.get("unit") == name:
            return unit
    return None


def build_closure(
    start: datetime,
    end: datetime,
    cutover: datetime,
    units: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    required_end = cutover + CLOSURE_WINDOW
    covers = start <= cutover and end >= required_end
    chat = get_unit(units, CHAT_UNIT)
    reasons: list[str] = []
    if not covers:
        reasons.append("window_does_not_cover_cutover_24h")
    if chat is None or not chat["journal"]["read"]:
        reasons.append("chat_journal_unreadable")
        nogil = None
        http = unavailable_http("journal_unreadable")
    else:
        nogil = chat["counts"]["nogil_occurrences"]
        http = chat["http_5xx"]
    pass_5479 = nogil == 0
    if nogil is None:
        reasons.append("nogil_unreadable")
    elif nogil > 0:
        reasons.append("nogil_recurrence")
    auth_status_5xx = http["focus"]["/api/auth/status"]
    projects_5xx = http["focus"]["/api/projects"]
    pass_6127 = bool(http["available"] and auth_status_5xx == 0 and projects_5xx == 0)
    if not http["available"]:
        reasons.append("chat_5xx_unavailable")
    elif not pass_6127:
        reasons.append("chat_focus_5xx")
    return {
        "cutover": iso(cutover),
        "required_window_end": iso(required_end),
        "window_covers_full_24h": covers,
        "issues": {
            "#5479": {
                "criterion": "padiem-chat-com2 NoGilError occurrences == 0",
                "observed_nogil_occurrences": nogil,
                "pass": pass_5479,
            },
            "#6127": {
                "criterion": "padiem-chat-com2 5xx at /api/auth/status and /api/projects == 0",
                "http_5xx_available": http["available"],
                "http_5xx_source": http["source"],
                "auth_status_5xx": auth_status_5xx,
                "projects_5xx": projects_5xx,
                "pass": pass_6127,
            },
        },
        "closeable": bool(covers and pass_5479 and pass_6127),
        "reasons": reasons,
    }


def build_report(
    start: datetime,
    end: datetime,
    cutover: datetime,
    units: Sequence[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "kind": KIND,
        "generated_at": iso(generated_at or datetime.now(timezone.utc)),
        "window": {
            "since": iso(start),
            "until": iso(end),
            "hours": round((end - start).total_seconds() / 3600.0, 3),
        },
        "units": list(units),
        "closure": build_closure(start, end, cutover, units),
    }


def count_or_na(value: Any) -> str:
    return "n/a" if value is None else str(value)


def issue_status(value: Mapping[str, Any]) -> str:
    if value.get("pass"):
        return "PASS"
    if "observed_nogil_occurrences" in value:
        return "UNKNOWN" if value["observed_nogil_occurrences"] is None else "FAIL"
    return "UNKNOWN" if value.get("http_5xx_available") is False else "FAIL"


def render_summary(report: Mapping[str, Any]) -> str:
    window = report["window"]
    closure = report["closure"]
    lines = [
        "PADIEM COM2 POST-CUTOVER REPORT (READ-ONLY)",
        "window: %s .. %s (%.3fh)" % (window["since"], window["until"], window["hours"]),
        "cutover: %s  full_24h=%s" % (closure["cutover"], "YES" if closure["window_covers_full_24h"] else "NO"),
        "",
        "%-18s %-10s %8s %9s %6s %10s %8s %8s %10s"
        % ("unit", "active", "restarts", "traceback", "ERROR", "NoGilError", "PyProxy", "5xx", "health"),
    ]
    detail: list[str] = []
    for unit in report["units"]:
        counts = unit["counts"] or {}
        http = unit["http_5xx"]
        health = unit["health"]
        five = count_or_na(http.get("total"))
        health_label = health.get("status", "UNKNOWN")
        if health.get("http_status") is not None:
            health_label += "/%s" % health["http_status"]
        lines.append(
            "%-18s %-10s %8s %9s %6s %10s %8s %8s %10s"
            % (
                unit["unit"],
                unit["systemd"].get("active_state") or "unknown",
                count_or_na(unit["systemd"].get("n_restarts")),
                count_or_na(counts.get("tracebacks")),
                count_or_na(counts.get("error_lines")),
                count_or_na(counts.get("nogil_occurrences")),
                count_or_na(counts.get("pyproxy_occurrences")),
                five,
                health_label,
            )
        )
        if http.get("available"):
            routes = ",".join("%s=%d" % item for item in http.get("by_route", {}).items()) or "-"
            detail.append(
                "  %s: source=%s requests=%d total=%d routes=%s"
                % (unit["unit"], http["source"], http["request_records"], http["total"], routes)
            )
        else:
            detail.append("  %s: 5xx 집계 불가 (%s)" % (unit["unit"], http.get("reason")))
    lines.extend(["", "5xx detail:"])
    lines.extend(detail)
    issues = closure["issues"]
    lines.append("")
    lines.append(
        "closure: #5479=%s #6127=%s full_24h=%s closeable=%s"
        % (
            issue_status(issues["#5479"]),
            issue_status(issues["#6127"]),
            "YES" if closure["window_covers_full_24h"] else "NO",
            "YES" if closure["closeable"] else "NO",
        )
    )
    if closure["reasons"]:
        lines.append("reasons: %s" % ",".join(closure["reasons"]))
    return "\n".join(lines)


def parse_health_overrides(values: Sequence[str]) -> dict[str, str]:
    urls = dict(DEFAULT_HEALTH_URLS)
    for value in values:
        unit, separator, url = value.partition("=")
        if not separator or unit not in urls or not url:
            raise ValueError("health-url must be UNIT=URL for a known unit")
        urls[unit] = url
    return urls


def collect_unit(
    unit: str,
    start: datetime,
    end: datetime,
    health_url: str | None,
    *,
    journalctl: str = "journalctl",
    systemctl: str = "systemctl",
    health_timeout: float = 5.0,
) -> dict[str, Any]:
    journal_text, journal_error = read_command(journalctl_argv(unit, start, end, journalctl), timeout=120)
    props_text, _props_error = read_command(systemctl_argv(unit, systemctl), timeout=15)
    health = probe_health(health_url, health_timeout) if health_url else None
    return observe_unit(unit, journal_text, journal_error, props_text, health)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="ISO-8601 window start; default: 24 hours before --until")
    parser.add_argument("--until", help="ISO-8601 window end; default: now")
    parser.add_argument("--cutover", default=DEFAULT_CUTOVER, help="cutover moment used for the 24-hour closure gate")
    parser.add_argument("--json-out", help="write the JSON report to this path")
    parser.add_argument("--health-url", action="append", default=[], metavar="UNIT=URL")
    parser.add_argument("--no-health", action="store_true")
    parser.add_argument("--health-timeout", type=float, default=5.0)
    parser.add_argument("--journalctl", default="journalctl")
    parser.add_argument("--systemctl", default="systemctl")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        now = datetime.now(timezone.utc)
        start, end = resolve_window(args.since, args.until, now)
        cutover = parse_moment(args.cutover)
        health_urls = {} if args.no_health else parse_health_overrides(args.health_url)
    except ValueError as exc:
        print("POST_CUTOVER_REPORT=INVALID_ARGUMENT %s" % exc, file=sys.stderr)
        return 2
    observations = [
        collect_unit(
            unit,
            start,
            end,
            health_urls.get(unit),
            journalctl=args.journalctl,
            systemctl=args.systemctl,
            health_timeout=args.health_timeout,
        )
        for unit in UNITS
    ]
    report = build_report(start, end, cutover, observations)
    print(render_summary(report))
    rendered = json.dumps(report, ensure_ascii=True, sort_keys=True)
    print(rendered)
    if args.json_out:
        try:
            Path(args.json_out).write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            print("POST_CUTOVER_REPORT=WRITE_FAILED %s" % type(exc).__name__, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
