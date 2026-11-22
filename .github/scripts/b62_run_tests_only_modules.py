#!/usr/bin/env python3
"""Run selected pytest modules in separate, bounded processes with live logs."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

MODULE_TIMEOUT_SECONDS = 120
TIMEOUT_EXIT = 124


def run_modules(modules, *, timeout_seconds=MODULE_TIMEOUT_SECONDS, command=None):
    command = command or (sys.executable, "-u", "-m", "pytest", "-q")
    if not modules:
        print("B62_TESTS_ONLY=EMPTY", flush=True)
        return 1
    for index, module in enumerate(modules, 1):
        start = time.monotonic()
        print(f"B62_TEST_MODULE_START {index}/{len(modules)} {module} timeout={timeout_seconds}s",
              flush=True)
        process = subprocess.Popen([*command, module], start_new_session=os.name == "posix")
        timed_out = False
        try:
            rc = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            # On Linux CI kill the whole pytest process group (including
            # test-launched children), not just the parent process.
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait()
            rc = TIMEOUT_EXIT
        status = "TIMEOUT" if timed_out else "PASS" if rc == 0 else "FAIL"
        print(f"B62_TEST_MODULE_END {index}/{len(modules)} {module} "
              f"status={status} exit={rc} elapsed={time.monotonic() - start:.2f}s",
              flush=True)
        if rc:
            return rc if rc > 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(run_modules(sys.argv[1:]))
