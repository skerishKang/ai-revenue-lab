#!/usr/bin/env python3
"""#3989: run all B62 visual evidence suites without concurrent Chromium processes.

The preceding eight browser-qa scripts retain their original sequential steps.
These three page-local visual suites run in their original sequential order: each opens its own
Playwright browser/context and writes a unique prefixed screenshot/report family
in the existing artifact folder. No suites or assertions are deleted.
"""
from __future__ import annotations

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


def main() -> int:
    # #4101: GitHub-hosted 2-core runners dropped to 6.6/7.8 FPS when
    # shell and zoom Chromium processes overlapped. Serialize on this
    # runner; keep all three full suites, reports and hard failure fan-in.
    # Each child inherits the mock-only environment of the original steps.
    assert len(SCRIPTS) == len(set(SCRIPTS)) == 3
    assert MAX_PARALLEL == 1 and len(SCRIPTS) == 3
    if os.environ.get("PADIEM_CHAT_RUNTIME_MODE") != "mock":
        print("B62_VISUAL_TAIL_REJECTED=NON_MOCK_RUNTIME", flush=True)
        return 1
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        futures = [pool.submit(execute, script) for script in SCRIPTS]
        results = [f.result() for f in futures]

    failed = []
    for name, rc, seconds, output in results:
        print(f"=== B62_VISUAL_TAIL_CASE={name} seconds={seconds:.2f} exit={rc} ===", flush=True)
        if output:
            print(output, end="\n" if not output.endswith("\n") else "", flush=True)
        if rc:
            failed.append(name)
        print(f"B62_VISUAL_TAIL_STATUS_{name}={'FAIL' if rc else 'PASS'}", flush=True)
    print(f"B62_VISUAL_TAIL_EXECUTED={len(results)}", flush=True)
    print(f"B62_VISUAL_TAIL_FAIL_COUNT={len(failed)}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
