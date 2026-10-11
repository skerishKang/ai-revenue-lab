"""Benchmark three deterministic B62 contract-test runs; no credentials needed."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "padiem-chat"
OUTPUT = ROOT / ".tmp" / "ci-runner-3990-benchmark.json"
CONTRACTS = [
    "tests/test_b62_1819_product_surface_certification.py",
    "tests/test_b62_1887_post_certification_hardening.py",
]


def run_trials() -> dict:
    # Refuse to use this benchmark with untrusted PR checkout/ref.
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("benchmark requires main ref; PR execution prohibited")
    if not (APP / "uv.lock").is_file():
        raise RuntimeError("missing committed uv.lock")
    outcomes = []
    for i in range(1, 4):
        started = time.monotonic()
        command = [
            "uv",
            "run",
            "--locked",
            "python",
            "-m",
            "pytest",
            "-q",
            *CONTRACTS,
        ]
        process = subprocess.run(
            command,
            cwd=APP,
            timeout=180,
            check=False,
            capture_output=True,
            text=True,
        )
        elapsed = round(time.monotonic() - started, 3)
        print(
            f"CI_3990_TRIAL_{i}: exit={process.returncode} "
            f"elapsed_seconds={elapsed}",
            flush=True,
        )
        if process.returncode:
            print(process.stdout[-2500:], file=sys.stderr)
            print(process.stderr[-2500:], file=sys.stderr)
        outcomes.append(
            {"trial": i, "seconds": elapsed, "returncode": process.returncode}
        )
        if process.returncode:
            break
    return {
        "schema": 1,
        "suite": "B62 deterministic source-contract smoke",
        "source_ref": os.environ.get("GITHUB_SHA", ""),
        "runner_os": platform.platform(),
        "python_version": platform.python_version(),
        "runner_name": os.environ.get("RUNNER_NAME", ""),
        "trials": outcomes,
        "all_passed": len(outcomes) == 3
        and all(item["returncode"] == 0 for item in outcomes),
    }


def main() -> int:
    result = run_trials()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("### #3990 CI runner benchmark (three trials)\n\n")
            stream.write("| Trial | Seconds | Exit code |\n|---|---:|---:|\n")
            for row in result["trials"]:
                stream.write(
                    f"| {row['trial']} | {row['seconds']} | {row['returncode']} |\n"
                )
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())