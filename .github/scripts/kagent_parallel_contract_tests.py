"""Run the complete KAgent unittest suite once, in two isolated local processes.

No coverage selection or sample mode: the controller discovers *every* unittest
case, proves an exact disjoint partition by test ID, and independently verifies
both child discoveries before allowing either suite to run. All skipped,
failed and import-error cases remain part of the normal unittest result.

The heavy HWPX group uses one child; the rest uses another. Separate Python
processes avoid cross-worker module monkeypatch/global state contamination.
This is parallelism inside the *same* GitHub Actions runner: no new billed jobs.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HEAVY_MODULES = frozenset(
    {
        "test_hwpx_skill_create",
        "test_hwpx_skill_edit",
        "test_hwpx_skill_insert_table",
        "test_hwpx_skill_template_fill",
    }
)
_GROUPS = ("heavy", "rest")


def _flatten(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def _discover() -> list[unittest.case.TestCase]:
    # unittest's ordinary discover() machinery is identical to the previous
    # CLI command; only the way the resulting cases are scheduled changes.
    suite = unittest.TestLoader().discover(start_dir="tests", pattern="test*.py")
    return list(_flatten(suite))


def _select(tests: list[unittest.case.TestCase], group: str):
    if group not in _GROUPS:
        raise ValueError("unknown KAgent test group")
    return [
        test
        for test in tests
        if (test.id().split(".", 1)[0] in _HEAVY_MODULES) == (group == "heavy")
    ]


def _digest(tests) -> str:
    # Include every test ID, sorted but never deduplicated. A duplicate or a
    # missing case changes the digest and therefore fails closed.
    ids = sorted(test.id() for test in tests)
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def _worker(group: str, expected_count: int, expected_digest: str) -> int:
    selected = _select(_discover(), group)
    actual_digest = _digest(selected)
    if len(selected) != expected_count or actual_digest != expected_digest:
        print(
            f"KAGENT_PARALLEL_DISCOVERY_MISMATCH group={group} "
            f"expected={expected_count}:{expected_digest} "
            f"actual={len(selected)}:{actual_digest}",
            file=sys.stderr,
        )
        return 2
    print(
        f"KAGENT_GROUP_BEGIN group={group} tests={len(selected)} "
        f"sha256={actual_digest}",
        flush=True,
    )
    # Python 3.12's TextTestRunner 'durations' provides the same per-test
    # profiling as the previous 'python -m unittest ... --durations=50'.
    runner = unittest.TextTestRunner(verbosity=2, durations=50)
    result = runner.run(unittest.TestSuite(selected))
    if result.testsRun != expected_count or not result.wasSuccessful():
        print(
            f"KAGENT_GROUP_FAILED group={group} "
            f"ran={result.testsRun} expected={expected_count} "
            f"failures={len(result.failures)} errors={len(result.errors)}",
            file=sys.stderr,
        )
        return 1
    print(
        f"KAGENT_GROUP_PASS group={group} tests={result.testsRun} "
        f"skipped={len(result.skipped)}",
        flush=True,
    )
    return 0


def _controller() -> int:
    # GitHub-hosted Windows can expose a cp1252 parent stdout even when the
    # workers write UTF-8 logs. Print those full Korean test logs as UTF-8,
    # preserving errors and diagnostics rather than truncating them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    discovered = _discover()
    groups = {group: _select(discovered, group) for group in _GROUPS}
    expected = len(discovered)
    if not groups["heavy"] or not groups["rest"]:
        print("KAGENT_PARALLEL_EMPTY_PARTITION", file=sys.stderr)
        return 2
    if sum(len(tests) for tests in groups.values()) != expected:
        print("KAGENT_PARALLEL_COUNT_MISMATCH", file=sys.stderr)
        return 2
    # Exact multiset identity: partition coverage must match ordinary
    # unittest discovery, regardless of duplicate IDs if they are deliberate.
    from collections import Counter

    if Counter(t.id() for t in discovered) != Counter(
        t.id() for tests in groups.values() for t in tests
    ):
        print("KAGENT_PARALLEL_ID_MISMATCH", file=sys.stderr)
        return 2

    print(
        f"KAGENT_SUITE_DISCOVERED total={expected} "
        + " ".join(f"{g}={len(groups[g])}" for g in _GROUPS),
        flush=True,
    )
    # Every subprocess re-discovers its cases and compares the exact sorted-ID
    # hash to the controller's. No test can silently drop on import differences.
    with tempfile.TemporaryDirectory(prefix="kagent-parallel-") as tmp:
        processes = []
        for group in _GROUPS:
            log = Path(tmp) / f"{group}.log"
            handle = log.open("w", encoding="utf-8")
            args = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                group,
                str(len(groups[group])),
                _digest(groups[group]),
            ]
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            try:
                process = subprocess.Popen(
                    args,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=os.getcwd(),
                    shell=False,
                )
            finally:
                handle.close()
            processes.append((group, process, log))
        results = [(group, proc.wait(), log) for group, proc, log in processes]
        for group, code, log in results:
            print(f"KAGENT_GROUP_LOG_START group={group} exit={code}", flush=True)
            print(log.read_text(encoding="utf-8", errors="replace"), flush=True)
            print(f"KAGENT_GROUP_LOG_END group={group}", flush=True)
        if any(code != 0 for _, code, _ in results):
            print("KAGENT_PARALLEL_FAILURE", file=sys.stderr)
            return 1
    print(f"KAGENT_FULL_SUITE_PASS total={expected} groups=2", flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        raise SystemExit(_worker(sys.argv[2], int(sys.argv[3]), sys.argv[4]))
    if len(sys.argv) != 1:
        raise SystemExit("usage: kagent_parallel_contract_tests.py")
    raise SystemExit(_controller())
