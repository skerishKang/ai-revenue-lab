#!/usr/bin/env python3
"""#4139: aggregate one `wrangler tail --format json` capture into counts only.

Nothing here prints a request body, a header, a cookie, a token or a full URL. The
whole point is that this file is safe to run against production traffic on a shared
CI log: outcome, exception signature, path and colo are the only things that leave.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from urllib.parse import urlsplit

#: Only whitelisted fields are ever read below: headers, cookies, bodies and tokens
#: are not on any path to the output, so a shared CI log stays safe.
_TOKENISH = re.compile(r"[0-9A-Za-z_+/$@.-]{24,}")
#: Key names that are never descended into or spelled out in the shape report.
HIDDEN_KEYS = frozenset({"headers", "cookie", "cookies", "authorization", "body",
                         "value", "token", "secret", "params", "query", "search"})
_BUCKETS = (
    ("exceededMemory", ("exceedmem", "exceededmemory", "oom", "memory")),
    ("exceededCpu", ("exceedcpu", "exceededcpu", "cpu")),
    ("limitDuration", ("duration", "timeout")),
    ("exception", ("exception", "error")),
    ("canceled", ("cancel", "abort", "gapped", "disconnect")),
    ("ok", ("ok", "success")),
)


def bucket(outcome: str) -> str:
    text = str(outcome or "").lower().replace("_", "").replace(" ", "")
    for name, marks in _BUCKETS:
        if any(mark in text for mark in marks):
            return name
    return "other:" + (str(outcome or "unknown")[:40])


def _texts(node, keys: set, depth: int = 0) -> list[str]:
    """Strings found under whitelisted key names, at bounded depth.

    The row shape moves; the allowlist does not. A header, a cookie or a request body
    has no key name on this list, so it cannot reach the output by any path.
    """

    found: list[str] = []
    if depth > 3:
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in keys and isinstance(value, str) and value.strip():
                found.append(value.strip())
            else:
                found.extend(_texts(value, keys, depth + 1))
    elif isinstance(node, list):
        for item in node:
            found.extend(_texts(item, keys, depth + 1))
    return found


def signature(row: dict) -> str | None:
    """One exception line, shortened and scrubbed of anything token-shaped."""

    parts = _texts(row.get("exceptions"), {"pattern", "message", "name", "reason"})
    parts += _texts(row.get("diagnosticsChannelEvents"),
                    {"pattern", "message", "name", "kind", "reason"})
    if not parts:
        parts = _texts(row.get("exception"), {"pattern", "message", "name"})
    if not parts:
        # A Python worker reports its cause in the first line of `stack`. Only that one
        # line: the frames below name files, not causes, and they are not the question.
        for stack in _texts(row.get("exceptions"), {"stack"}):
            head = next((line.strip() for line in stack.splitlines() if line.strip()), "")
            if head:
                parts.append(head)
                break
    if not parts:
        message = row.get("message")
        if isinstance(message, str) and message.strip():
            parts.append(message.strip())
    if not parts:
        return None
    text = " | ".join(dict.fromkeys(parts))
    text = text.split("?", 1)[0]
    text = _TOKENISH.sub("<tok>", text)
    return text[:140]


def path_of(row: dict) -> str | None:
    for url in _texts(row, {"url"}):
        path = urlsplit(url).path
        if path:
            return path[:80]
    return None


def key_shape(node, depth: int = 0, prefix: str = "") -> list[str]:
    """Key NAMES of a row, dot-joined to a bounded depth. Names, never values.

    The tail's row shape moved once already, so the capture prints this and the next
    read is written against what the Worker actually sent rather than against a guess.
    Keys that would carry credentials or request content are named once, then closed -
    even their names are only reported as an opaque slot.
    """

    names: list[str] = []
    if depth > 2:
        return names
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in HIDDEN_KEYS:
                names.append(prefix + "<hidden>")
                continue
            name = prefix + str(key)
            if isinstance(value, str):
                # The length is the diagnosis: the third capture showed the keys with no
                # text behind them, and a name alone cannot tell an empty field from a
                # field the extractor failed to read.
                names.append("%s=%dch" % (name, len(value)))
            elif isinstance(value, (int, bool)) or value is None:
                names.append("%s=%s" % (name, "int" if isinstance(value, int)
                                        else type(value).__name__))
            else:
                names.append(name)
            if isinstance(value, (dict, list)):
                names.extend(key_shape(value, depth + 1, name + "."))
    elif isinstance(node, list):
        for item in node[:1]:
            base = prefix.rstrip(".") + "[]"
            names.append(base)
            names.extend(key_shape(item, depth + 1, base + "."))
    return sorted(set(names))


def colo_of(row: dict) -> str | None:
    """The colo that served the request.

    The row does not name a colo at the top level; `event.request.cf` carries the
    Cloudflare request metadata, and the colo in it is what separates "one edge is
    sick" from "the Worker is sick everywhere". Only the three-letter code is read.
    """

    for value in _texts(row, {"colo", "coloCode"}):
        if value.strip():
            return value.strip().upper()[:8]
    for key in ("cololo", "colo", "coloCode", "colo_code"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()[:8]
    for holder in (row.get("trace"), row.get("location")):
        if isinstance(holder, dict):
            for key in ("colo", "coloCode"):
                value = holder.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip().upper()[:8]
    return None


def status_of(row: dict) -> str | None:
    """The response status the Worker answered with, wherever the row keeps it.

    This row shape puts it under `event.response.status`, not at the top level.
    """

    return _int_named(row, "status", depth=0)


def _int_named(node, name: str, depth: int) -> str | None:
    if depth > 3:
        return None
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() == name and isinstance(value, int):
                return str(value)
            found = _int_named(value, name, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _int_named(item, name, depth + 1)
            if found:
                return found
    return None


def summarize(rows: list[dict]) -> dict:
    outcomes: Counter = Counter()
    exceptions: Counter = Counter()
    paths: Counter = Counter()
    colos: Counter = Counter()
    statuses: Counter = Counter()
    fields: set[str] = set()
    shape: list[str] = []
    truncated = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        fields.update(str(key) for key in row
                      if str(key).lower() not in HIDDEN_KEYS)
        outcome = row.get("outcome") or row.get("level") or ""
        outcomes[bucket(outcome)] += 1
        if not shape and bucket(outcome) != "ok":
            shape = key_shape(row)
        if row.get("truncated") is True:
            truncated += 1
        sig = signature(row)
        if sig:
            exceptions[sig] += 1
        path = path_of(row)
        if path:
            paths[path] += 1
        colo = colo_of(row)
        if colo:
            colos[colo] += 1
        status = status_of(row)
        if status:
            statuses[status] += 1
    return {"rows": len(rows), "fields": sorted(fields), "outcomes": outcomes,
            "exceptions": exceptions, "paths": paths, "colos": colos,
            "statuses": statuses, "shape": shape, "truncated": truncated,
            "path_stats": path_stats(rows)}



#: Path segments that name an object, not a route: ids, tokens, dates, long
#: hex/uuid runs. They are folded to "*" so the bucket says which ENDPOINT was
#: slow without saying which user's object it was.
_IDISH = re.compile(r"^(?:\d+|[0-9a-f]{8,}|[0-9a-f]{8}-[0-9a-f-]{27,}"
                    r"|[a-z]+_[0-9a-f]{16,}"
                    r"|\d{4}-\d{2}-\d{2}[T_ ]?\d{0,6}|\d{4}-\d{2}-\d{2})$", re.I)


def path_bucket(path: str) -> str:
    parts = []
    for segment in str(path or "").split("/"):
        parts.append("*" if _IDISH.match(segment) else segment)
    return "/".join(parts)[:80] or "/"


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return float(ordered[index])


def _number(row: dict, name: str) -> float | None:
    value = row.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def sanitize_rows(rows: list[dict]) -> list[dict]:
    """The raw capture, reduced to the fields that answer "which route, how slow".

    Only path bucket, status, outcome, cpuTime, wallTime, scriptVersion id and
    the event timestamp are kept. Headers, cookies, bodies, URLs (query and
    user-carrying path segments included) and exception text never enter this
    file, so the artifact can be shared with the lane that reads baselines.
    """

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = path_of(row)
        outcome = str(row.get("outcome") or row.get("level") or "")
        version = row.get("scriptVersion")
        version_id = version.get("id") if isinstance(version, dict) else None
        entry: dict = {
            "path": path_bucket(path) if path else None,
            "status": status_of(row),
            "outcome": bucket(outcome),
            "cpuTime": _number(row, "cpuTime"),
            "wallTime": _number(row, "wallTime"),
            "version": str(version_id)[:36] if version_id else None,
            "ts": row.get("eventTimestamp") or row.get("timestamp"),
        }
        out.append({key: value for key, value in entry.items() if value is not None})
    return out


def path_stats(rows: list[dict]) -> dict:
    """Per path bucket: count, cpuTime p50/p95/max ms, and outcome tallies."""

    stats: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = path_of(row)
        if not path:
            continue
        key = path_bucket(path)
        item = stats.setdefault(key, {"cpu": [], "n": 0, "outcomes": Counter()})
        item["n"] += 1
        item["outcomes"][bucket(str(row.get("outcome") or ""))] += 1
        cpu = _number(row, "cpuTime")
        if cpu is not None:
            item["cpu"].append(cpu)
    return stats


def emit(summary: dict) -> None:
    print("TAIL_ROWS=%d" % summary["rows"])
    print("TAIL_FIELDS=%s" % ",".join(summary["fields"])[:400])
    if summary.get("shape"):
        print("SHAPE_KEYS=%s" % ";".join(summary["shape"])[:900])
        print("TAIL_TRUNCATED=%d/%d (a truncated row carries no text, so this is "
              "the difference between 'nothing threw' and 'the row was cut')"
              % (summary.get("truncated", 0), summary["rows"]))
    if not summary["rows"]:
        print("TAIL_EMPTY=1 (no messages captured: the tail saw no traffic, "
              "or wrangler refused to start)")
        return
    print("OUTCOMES " + " ".join("%s=%d" % item for item in
                                summary["outcomes"].most_common()))
    print("STATUS " + " ".join("%s=%d" % item for item in
                               summary["statuses"].most_common(8)))
    print("EXCEPTION_TOP5")
    for text, count in summary["exceptions"].most_common(5):
        print("  %d | %s" % (count, text))
    print("PATH_TOP10")
    for path, count in summary["paths"].most_common(10):
        print("  %d | %s" % (count, path))
    stats = summary.get("path_stats") or {}
    if stats:
        print("PATH_CPU_TOP10 (ms; * = id segment folded)")
        for key, item in sorted(stats.items(), key=lambda kv: -kv[1]["n"])[:10]:
            cpu = item["cpu"]
            outs = " ".join("%s=%d" % kv for kv in item["outcomes"].most_common())
            print("  %-40s n=%d p50=%.1f p95=%.1f max=%.1f %s"
                  % (key, item["n"], _percentile(cpu, 0.50), _percentile(cpu, 0.95),
                     max(cpu) if cpu else 0.0, outs))
    if summary["colos"]:
        print("COLO " + " ".join("%s=%d" % item for item in
                                 summary["colos"].most_common(10)))
    else:
        print("COLO_UNAVAILABLE=tail did not carry a colo field")


def load(path: str) -> list[dict]:
    """Read a capture as a stream of JSON values.

    `wrangler tail --format json` pretty-prints one JSON array across many lines, while
    other builds emit one object per line. Both are read here: values are decoded where
    they start, and anything that is not JSON (wrangler's own header lines) is skipped.
    """

    text = open(path, encoding="utf-8", errors="replace").read()
    decoder = json.JSONDecoder()
    rows: list[dict] = []
    index = 0
    while index < len(text):
        if text[index] in " \t\r\n,[]":
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            newline = text.find("\n", index)
            if newline < 0:
                break
            index = newline + 1
            continue
        if isinstance(value, dict):
            rows.append(value)
        elif isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
        index = end
    return rows


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: b62_tail_summarize.py <tail.jsonl> [--sanitize-out PATH]")
        return 2
    rows = load(argv[1])
    emit(summarize(rows))
    if "--sanitize-out" in argv:
        out_path = argv[argv.index("--sanitize-out") + 1]
        with open(out_path, "w", encoding="utf-8") as handle:
            for entry in sanitize_rows(rows):
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + chr(10))
        print("TAIL_SANITIZED_ROWS=%d" % len(sanitize_rows(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
