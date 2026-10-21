#!/usr/bin/env python3
"""#3989: run all B62 visual evidence suites without concurrent Chromium processes.

The preceding eight browser-qa scripts retain their original sequential steps.
These three page-local visual suites run in their original sequential order: each opens its own
Playwright browser/context and writes a unique prefixed screenshot/report family
in the existing artifact folder. No suites or assertions are deleted.

The runner has two lane scopes:

* ``--scope full`` runs the complete three-suite visual-tail contract.  This is
  the GitHub-hosted browser QA lane's scope: it runs on every pull request and
  is where the Glass Zoom suite proves the 2560x1440 Glass composition.
* ``--scope isolated`` (the default) runs the suites that fit the isolated
  COM2 container: the Glass Shell and Chat Gutter composition checks.  The
  high-resolution Glass Zoom suite is skipped there because the hosted lane
  already validates it on every pull request, and the same suite has never
  completed inside the isolated 1-CPU/768MB container's budgets (measured: the
  240s per-suite cap, and a fail-closed fan-in that turned the whole COM2
  canary red so the lane's other suites stopped producing a signal).

The default is the isolated scope because the isolated lane runs through a
root-owned host command that cannot pass an argument, while the hosted lane
owns its own invocation and opts into the full scope explicitly.  A skipped
suite is never counted as executed or passed: the skip is printed with its
reason and the hosted coverage that replaces it.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic


SCRIPTS = (
    "b62_glass_shell_visual_qa.py",
    "b62_glass_zoom_visual_qa.py",
    "b62_chat_gutter_visual_qa.py",
)
MAX_PARALLEL = 1
TIMEOUT_SECONDS = 240
SCRIPT_DIR = Path(__file__).resolve().parent

FULL_SCOPE = "full"
ISOLATED_SCOPE = "isolated"
SCOPES = (FULL_SCOPE, ISOLATED_SCOPE)
DEFAULT_SCOPE = ISOLATED_SCOPE
SCOPE_SUITES = {
    FULL_SCOPE: SCRIPTS,
    ISOLATED_SCOPE: (
        "b62_glass_shell_visual_qa.py",
        "b62_chat_gutter_visual_qa.py",
    ),
}
SKIP_REASON = (
    "the high-resolution Glass Zoom visual tail is validated by the GitHub-hosted "
    "browser QA lane on every pull request; the isolated 1-CPU/768MB container "
    "cannot render the 2560x1440 Glass surface inside its budgets"
)
HOSTED_COVERAGE = (
    ".github/workflows/b62-browser-qa-unified.yml browser-qa job "
    "(b62_browser_qa_tail_parallel.py --scope full)"
)


def resolve_scope(argv: list[str]) -> str:
    """Resolve the lane scope.

    An unknown scope value is refused by the parser (fail closed).  An
    unrelated argument is reported and ignored, so a host command that owns
    this script's invocation cannot break the lane by adding one.
    """

    parser = argparse.ArgumentParser(description="Run the B62 visual evidence suites.")
    parser.add_argument("--scope", choices=SCOPES, default=DEFAULT_SCOPE)
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"B62_VISUAL_TAIL_IGNORED_ARGUMENTS={' '.join(unknown)}", flush=True)
    return args.scope


def execute(script_name: str) -> tuple[str, int, float, str]:
    """Run an unchanged full source suite using this runner's existing venv."""
    start = monotonic()
    command = [sys.executable, str(SCRIPT_DIR / script_name)]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        return script_name, result.returncode, monotonic() - start, result.stdout or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return script_name, 124, monotonic() - start, out + "\nTIMED_OUT=YES\n"
    except OSError as exc:
        return script_name, 127, monotonic() - start, f"SPAWN_FAILED={exc}\n"


def main(argv: list[str] | None = None) -> int:
    # #4101: GitHub-hosted 2-core runners dropped to 6.6/7.8 FPS when
    # shell and zoom Chromium processes overlapped. Serialize on this
    # runner; keep all three full suites, reports and hard failure fan-in.
    # Each child inherits the mock-only environment of the original steps.
    scope = resolve_scope(list(sys.argv[1:] if argv is None else argv))
    suites = SCOPE_SUITES[scope]
    skipped = [name for name in SCRIPTS if name not in suites]
    assert len(SCRIPTS) == len(set(SCRIPTS)) == 3
    assert MAX_PARALLEL == 1 and len(SCRIPTS) == 3
    assert suites and set(suites) <= set(SCRIPTS)
    if os.environ.get("PADIEM_CHAT_RUNTIME_MODE") != "mock":
        print("B62_VISUAL_TAIL_REJECTED=NON_MOCK_RUNTIME", flush=True)
        return 1
    print(f"B62_VISUAL_TAIL_SCOPE={scope}", flush=True)
    print(f"B62_VISUAL_TAIL_PLANNED={len(suites)}", flush=True)
    for name in skipped:
        print(f"B62_VISUAL_TAIL_SKIPPED={name}", flush=True)
        print(f"B62_VISUAL_TAIL_SKIP_REASON={SKIP_REASON}", flush=True)
        print(f"B62_VISUAL_TAIL_HOSTED_COVERAGE={HOSTED_COVERAGE}", flush=True)
    failed = []
    # Each case is printed as soon as it finishes, in the suite order.  The
    # COM2 runner keeps a bounded log window and can cut the job off while
    # the tail is still running, so a suite that already finished has to be
    # visible before the next one starts.  The suites, their order, their
    # timeouts and the hard failure fan-in are unchanged.
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        futures = [pool.submit(execute, script) for script in suites]
        results = []
        for future in futures:
            name, rc, seconds, output = future.result()
            results.append((name, rc, seconds, output))
            print(f"=== B62_VISUAL_TAIL_CASE={name} seconds={seconds:.2f} exit={rc} ===", flush=True)
            if output:
                print(output, end="\n" if not output.endswith("\n") else "", flush=True)
            if rc:
                failed.append(name)
            print(f"B62_VISUAL_TAIL_STATUS_{name}={'FAIL' if rc else 'PASS'}", flush=True)
    # A failing suite's assertion has to survive the bounded diagnostic window
    # the COM2 runner keeps (the last N log lines only), so repeat the failing
    # case's evidence tail after every suite has already printed.  The suite
    # itself is unchanged; only the failure evidence is repeated.
    for name, rc, seconds, output in results:
        if not rc:
            continue
        print(
            f"=== B62_VISUAL_TAIL_FAILURE={name} exit={rc} seconds={seconds:.2f} ===",
            flush=True,
        )
        for line in (output or "").strip().splitlines()[-12:]:
            print(f"B62_VISUAL_TAIL_FAILURE_LINE={line}", flush=True)
    print(f"B62_VISUAL_TAIL_EXECUTED={len(results)}", flush=True)
    print(f"B62_VISUAL_TAIL_SKIPPED_COUNT={len(skipped)}", flush=True)
    print(f"B62_VISUAL_TAIL_FAIL_COUNT={len(failed)}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
