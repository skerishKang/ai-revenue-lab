#!/usr/bin/env python3
"""Materialize the exact accepted Lane A snapshot for Lane B builders.

Deterministically extracts every file listed in accepted_source.py from
``git show 63adbefc:<path>`` into
``validation/.accepted_source/63adbefc.../`` and prints per-file SHA256.
Fails closed when the revision or any file is unavailable. Lane A files
are only read, never modified.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from accepted_source import (  # noqa: E402
    ACCEPTED_SOURCE_FILES,
    ACCEPTED_SOURCE_REVISION,
    CACHE_DIR,
    find_repo_root,
    materialize,
)


def main() -> int:
    repo = find_repo_root(Path(__file__).resolve())
    snapshot = materialize(repo)
    print(f"SOURCE_REVISION={ACCEPTED_SOURCE_REVISION}")
    for name in ACCEPTED_SOURCE_FILES:
        digest = hashlib.sha256((CACHE_DIR / name).read_bytes()).hexdigest()
        print(f"{digest}  {name} ({len(snapshot[name].splitlines())} lines)")
    print(f"materialized {len(snapshot)} files -> {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
