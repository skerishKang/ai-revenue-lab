#!/usr/bin/env python3
"""Read-only rollup of the per-turn metrics line (#6812).

The Chat service writes one ``ai_stage`` / ``turn.summary`` line per answered
/api/orchestration turn. This script reads those lines from a file or stdin and
prints success rate by grade and by web-search use, first-byte p50/p90, and
success rate by evidence-length bucket. It never writes, never calls a service
and never prints prompt or answer text.

Usage:
    journalctl -u padiem-chat-com2 --since '24 hours ago' --no-pager \
        | python scripts/turn_metrics_report.py
    python scripts/turn_metrics_report.py chat-log.jsonl
"""
from __future__ import annotations

import json
import sys
from typing import Any, Iterable


def _turns(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in lines:
        start = line.find("{")
        if start < 0:
            continue
        try:
            event = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") != "ai_stage" or event.get("stage") != "turn.summary":
            continue
        metrics = event.get("metrics")
        if not isinstance(metrics, dict):
            continue
        yield {"event": event, "metrics": metrics, "ok": event.get("outcome") == "ok"}


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def _bucket(chars: Any) -> str:
    if not isinstance(chars, (int, float)):
        return "unknown"
    if chars == 0:
        return "0"
    if chars <= 4_000:
        return "1-4000"
    if chars <= 12_000:
        return "4001-12000"
    return "12001+"


def _rate(rows: list[dict[str, Any]]) -> str:
    ok = sum(1 for row in rows if row["ok"])
    return f"{ok}/{len(rows)}" + (f" ({ok * 100 / len(rows):.0f}%)" if rows else "")


def report(rows: list[dict[str, Any]]) -> str:
    out: list[str] = [f"turns: {len(rows)}"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        metrics = row["metrics"]
        key = (str(metrics.get("tier") or "unknown"),
               "search" if metrics.get("web_search") else "no-search")
        groups.setdefault(key, []).append(row)

    out.append("")
    out.append(f"{'group':<22}{'turns':>6}{'ok':>13}{'ttft p50':>11}{'ttft p90':>11}")
    for (tier, searched), items in sorted(groups.items()):
        ttft = [item["metrics"]["first_byte_ms"] for item in items
                if isinstance(item["metrics"].get("first_byte_ms"), (int, float))]
        p50 = _percentile(ttft, 0.5)
        p90 = _percentile(ttft, 0.9)
        out.append(
            f"{tier + '/' + searched:<22}{len(items):>6}{_rate(items):>13}"
            f"{(f'{p50:.0f}ms' if p50 is not None else '-'):>11}"
            f"{(f'{p90:.0f}ms' if p90 is not None else '-'):>11}"
        )

    out.append("")
    out.append("[evidence chars -> success]")
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(_bucket(row["metrics"].get("evidence_chars")), []).append(row)
    for name in ("0", "1-4000", "4001-12000", "12001+", "unknown"):
        items = buckets.get(name)
        if items:
            out.append(f"{name:<12}{_rate(items):>16}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8", errors="replace") as handle:
            rows = list(_turns(handle))
    else:
        rows = list(_turns(sys.stdin))
    print(report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
