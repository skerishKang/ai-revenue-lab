#!/usr/bin/env python3
"""Scope check for the Business 32 Phase 2 UX workspace.

Verifies that every changed path (committed, staged, unstaged, untracked)
stays inside reference/business-32-ai-skill-studio-ux/** and that Phase 1
files (PR #251 workspace) are never touched.
"""
import subprocess
import sys

ALLOWED = "reference/business-32-ai-skill-studio-ux/"
FORBIDDEN = "reference/business-32-ai-skill-studio-v1/"

failures = []


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def paths_from_status():
    out = run(["git", "status", "--porcelain", "--untracked-files=all"]).stdout
    for line in out.splitlines():
        if not line.strip():
            continue
        entry = line[3:].strip()
        entry = entry.split(" -> ")[-1]
        yield entry


def paths_from_diff():
    out = run(["git", "diff", "--name-only", "origin/main", "HEAD"]).stdout
    for line in out.splitlines():
        if line.strip():
            yield line.strip()


def main():
    changed = set()
    for p in paths_from_status():
        changed.add(p)
    for p in paths_from_diff():
        changed.add(p)

    if not changed:
        print("SCOPE: no changes detected")
        return 0

    print("Changed paths (%d):" % len(changed))
    for p in sorted(changed):
        print("  " + p)
        if not p.startswith(ALLOWED):
            failures.append("outside allowed scope: %s" % p)
        if p.startswith(FORBIDDEN):
            failures.append("Phase 1 workspace touched: %s" % p)

    if failures:
        for f in failures:
            print("FAIL " + f)
        return 1

    print("SCOPE: all changes inside %s" % ALLOWED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
