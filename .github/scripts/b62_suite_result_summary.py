#!/usr/bin/env python3
"""Publish one pytest suite's pass/fail counts to stdout and the run summary.

Used by the #5678 main-push baseline jobs (Engine and B14 whole suites), which
are informational at first: the suite exit status is recorded by the caller and
re-surfaced after this summary exists, so a failure that predates those jobs is
reported instead of silently gating the push.

Reads only the captured log file it is handed. It never opens a network
connection, never reads an environment secret and never re-runs anything.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _count(text: str, word: str) -> int:
    hits = re.findall(r"(\d+) " + word + r"s?\b", text)
    return int(hits[-1]) if hits else 0


def _failing_tests(text: str) -> list[str]:
    """Return node ids from the short summary, or section headers without them."""
    failures = re.findall(r"^FAILED (\S+)", text, re.MULTILINE)
    if failures:
        return failures
    return re.findall(r"^_+ (.+?) _+ *$", text, re.MULTILINE)


def main(argv: list[str]) -> int:
    log_path, label, prefix = Path(argv[0]), argv[1], argv[2]
    text = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.is_file()
        else ""
    )
    counts = {name: _count(text, name) for name in ("passed", "failed", "error", "skipped")}
    failures = _failing_tests(text)

    for name, value in counts.items():
        print(f"{prefix}_{name.upper()}={value}")
    print(f"{prefix}_FAILURES_LISTED={len(failures)}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(f"## {label} full regression (baseline, non-blocking)\n\n")
            handle.write(f"- passed: {counts['passed']}\n")
            handle.write(f"- failed: {counts['failed']}\n")
            handle.write(f"- errors: {counts['error']}\n")
            handle.write(f"- skipped: {counts['skipped']}\n")
            handle.write(f"- suite exit status: {os.environ.get(f'{prefix}_STATUS', 'unknown')}\n\n")
            if failures:
                handle.write(
                    "### Failing tests (pre-existing baseline; not fixed by this change)\n\n"
                )
                for name in failures:
                    handle.write(f"- `{name}`\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
