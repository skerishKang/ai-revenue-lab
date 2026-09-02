#!/usr/bin/env python3
"""Harness runner for B35 Independent QA - Lane C #1505

Discovers commercial/package roots, runs the validator, collects env evidence,
and ensures the harness never edits commercial source or generated artifacts.

This runner is the entry point for local and CI validation. Final PASS must
still be against the exact accepted #1503 source + exact #1504 package; this
runner will surface FAIL/UNAVAILABLE until those dependencies exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent

def git_rev(path: Path, rev: str = "HEAD") -> str:
    try:
        out = subprocess.run(["git", "rev-parse", rev], cwd=path, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"

def git_status(path: Path) -> str:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except Exception:
        return ""

def main() -> int:
    parser = argparse.ArgumentParser(description="Run B35 Independent QA harness")
    parser.add_argument("--commercial-root", default="docs/commercial/business-35-ai-media-education-dx")
    parser.add_argument("--package-root", default="docs/commercial/business-35-ai-media-education-dx/customer-package")
    parser.add_argument("--product-contract", default="reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md")
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--output-json", default="tools/b35-independent-qa/evidence/qa_report.json")
    parser.add_argument("--output-md", default="tools/b35-independent-qa/evidence/qa_report.md")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    print("=" * 72)
    print("B35 Independent QA Harness Runner - Lane C #1505")
    print("=" * 72)
    print(f"Tool dir        : {TOOL_DIR}")
    print(f"Repo root       : {ROOT}")
    print(f"Python          : {platform.python_version()} ({sys.executable})")
    print(f"Git HEAD        : {git_rev(ROOT, 'HEAD')}")
    print(f"Git origin/main : {git_rev(ROOT, 'origin/main')}")
    print(f"Git status      : {git_status(ROOT)[:200] or 'clean'}")
    print(f"Time            : {datetime.now(timezone.utc).isoformat()}")
    print()

    # Invoke validator
    validator = TOOL_DIR / "validate_b35_independent_qa.py"
    cmd = [
        sys.executable, str(validator),
        "--commercial-root", args.commercial_root,
        "--package-root", args.package_root,
        "--product-contract", args.product_contract,
        "--output-json", args.output_json,
        "--output-md", args.output_md,
    ]
    if args.manifest:
        cmd.extend(["--manifest", args.manifest])
    if args.pretty:
        cmd.append("--pretty")

    print(f"Running: {' '.join(cmd)}")
    print("-" * 72)
    proc = subprocess.run(cmd)
    print("-" * 72)
    print(f"Validator exit code: {proc.returncode}")

    # Also check harness independence: ensure validator did not modify commercial/package roots
    # We compare git diff for those paths
    try:
        out = subprocess.run(["git", "diff", "--name-only", "--", args.commercial_root, args.package_root], cwd=ROOT, capture_output=True, text=True, timeout=5)
        if out.stdout.strip():
            print(f"WARNING: validator modified commercial/package paths: {out.stdout.strip()}")
        else:
            print("Independence check: no commercial/package files modified by harness (OK)")
    except Exception as e:
        print(f"Independence check skipped: {e}")

    # Write runner evidence
    evidence_dir = Path(args.output_json).parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
    runner_json = evidence_dir / "runner_env.json"
    runner_json.write_text(json.dumps({
        "issue": 1505,
        "lane": "C",
        "branch": "feat/b35-w3-independent-qa-v31",
        "base_sha": "eae88e0066c1b119bfa6c75d8b16c127b0137e5e",
        "head_sha": git_rev(ROOT, "HEAD"),
        "origin_main": git_rev(ROOT, "origin/main"),
        "product_commit": "05932da3af774220372f0e9f3716b07cd83511f9",
        "commercial_root": args.commercial_root,
        "package_root": args.package_root,
        "validator_exit": proc.returncode,
        "time": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Runner evidence: {runner_json}")

    return proc.returncode

if __name__ == "__main__":
    sys.exit(main())
