"""#6724 시나리오 6 — 매일 도는 격리 Chat 복구 스모크.

복구 스크립트의 계약 시험 묶음을 임시 백업·시험 키로 실행한다. 운영 계정,
실제 DB, 오프사이트 키 파일, 결제는 쓰지 않는다. 모든 업스트림은 닫힌
loopback 포트에 머문다. 실패는 `USAGE_FLOW name=restore_smoke` 한 줄로 남겨
nightly-qa-failure-issue 가 흐름 이름을 붙여 이슈를 만들 수 있게 한다.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "deploy" / "host-com2" / "offsite-backup" / "tests" / "test_restore_script.py"
TIMEOUT_SECONDS = 180


def _verdict(stdout: str, returncode: int) -> tuple[str, str]:
    ran = re.search(r"^Ran (\d+) tests?", stdout, re.MULTILINE)
    skipped = re.search(r"skipped=(\d+)", stdout)
    count = int(ran.group(1)) if ran else 0
    skips = int(skipped.group(1)) if skipped else 0
    if returncode != 0:
        return "FAIL", "restore_test_failure"
    if count == 0:
        return "FAIL", "restore_no_tests"
    if skips >= count:
        return "SKIPPED", "restore_all_skipped"
    return "PASS", "restore_ok"


def main() -> int:
    started = time.monotonic()
    if not BUNDLE.is_file():
        verdict, code = "FAIL", "restore_bundle_missing"
    else:
        try:
            done = subprocess.run(
                [sys.executable, "-m", "unittest", str(BUNDLE), "-v"],
                cwd=str(REPO), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            verdict, code = "FAIL", "restore_timeout"
        except Exception as exc:
            verdict, code = "FAIL", "restore_runner_error_" + type(exc).__name__
        else:
            verdict, code = _verdict(done.stdout + done.stderr, done.returncode)
    elapsed = int((time.monotonic() - started) * 1000)
    print(f"USAGE_FLOW name=restore_smoke verdict={verdict} elapsed_ms={elapsed} code={code}")
    return 0 if verdict in ("PASS", "SKIPPED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
