#!/usr/bin/env python3
"""Import a private manifest using the existing COM2 operator runtime.

Use --apply to write; without it only validate the input. Input may be stdin
so the private manifest remains outside the repository. Output contains counts only.
"""
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from feedback_ops import (_assert_root, _load_env_file, _use_deployed_tree,
                          _become_service_user, _load_state, CHAT_ENV_PATH)


async def run_import(store, records):
    before, cursor = await store.list_entries(site="miraen-home")
    total_before = len(before)
    while cursor:
        page, cursor = await store.list_entries(site="miraen-home", cursor=cursor)
        total_before += len(page)
    inserted = 0
    for item in records:
        _, created = await store.import_miraen(**item)
        inserted += int(created)
    counts = Counter()
    cursor = None
    while True:
        page, cursor = await store.list_entries(site="miraen-home", cursor=cursor)
        counts.update(row.status for row in page)
        if not cursor:
            break
    return {"before": total_before, "inserted": inserted, "after": sum(counts.values()),
            "statuses": dict(counts)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="private JSON path or - for stdin")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.manifest == "-" else Path(args.manifest).read_text(encoding="utf8")
        records = json.loads(raw)
        if not isinstance(records, list) or not records:
            raise ValueError()
        keys = [row["external_key"] for row in records]
        if len(set(keys)) != len(keys):
            raise ValueError()
        if not args.apply:
            print(json.dumps({"records": len(records), "apply": False}))
            return 0
        _assert_root()
        _load_env_file(CHAT_ENV_PATH)
        _use_deployed_tree()
        _become_service_user()
        store = _load_state().site_feedback_store
        result = asyncio.run(run_import(store, records))
        print(json.dumps(result))
        return 0
    except Exception:
        print("STOP MIRAEN_IMPORT_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
