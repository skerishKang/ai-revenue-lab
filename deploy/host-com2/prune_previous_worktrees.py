#!/usr/bin/env python3
"""Keep only the newest rollback worktrees after a successful deployment.

The release currently rolling out is never a removal candidate. The script
touches only directories inside the configured previous root.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

KEEP = 10


def prune(root: Path, protected: str = "", keep: int = KEEP) -> int:
    root = Path(root).resolve()
    entries = [p for p in root.iterdir()
               if p.is_dir() and p.name != protected]
    entries.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    remove_count = keep - (1 if protected else 0)
    removed = 0
    for path in entries[max(remove_count, 0):]:
        if protected and path.name == protected:
            continue
        shutil.rmtree(path)
        removed += 1
    return removed


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: prune_previous_worktrees.py <previous-dir> [protected-sha] [keep]", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    protected = sys.argv[2] if len(sys.argv) > 2 else ""
    keep = int(sys.argv[3]) if len(sys.argv) > 3 else KEEP
    if not root.is_dir():
        print(f"PREVIOUS_ROOT=MISSING {root}", file=sys.stderr)
        return 1
    removed = prune(root, protected, keep)
    print(f"PREVIOUS_PRUNED={removed}")
    print(f"PREVIOUS_KEPT={keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
