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
    for key in ("status", "statusCode", "status_code"):
        value = row.get(key)
        if isinstance(value, int):
            return str(value)
    return None


def summarize(rows: list[dict]) -> dict:
    outcomes: Counter = Counter()
    exceptions: Counter = Counter()
    paths: Counter = Counter()
    colos: Counter = Counter()
    statuses: Counter = Counter()
    fields: set[str] = set()
    shape: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fields.update(str(key) for key in row
                      if str(key).lower() not in HIDDEN_KEYS)
        outcome = row.get("outcome") or row.get("level") or ""
        outcomes[bucket(outcome)] += 1
        if not shape and bucket(outcome) != "ok":
            shape = key_shape(row)
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
            "statuses": statuses, "shape": shape}


def emit(summary: dict) -> None:
    print("TAIL_ROWS=%d" % summary["rows"])
    print("TAIL_FIELDS=%s" % ",".join(summary["fields"])[:400])
    if summary.get("shape"):
        print("SHAPE_KEYS=%s" % ";".join(summary["shape"])[:900])
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
        print("usage: b62_tail_summarize.py <tail.jsonl>")
        return 2
    emit(summarize(load(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
