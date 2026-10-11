#!/usr/bin/env python3
"""Construct the Cloudflare Workers *deployment* rollback request, offline only.

Official Create Worker Deployment requires strategy='percentage' plus a
versions array. This script NEVER invokes Cloudflare, retries, or accesses
secrets. It fails closed on malformed version UUIDs and existing output files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID


def make_payload(version_id: str) -> dict[str, object]:
    if not isinstance(version_id, str):
        raise ValueError("version_id must be a string")
    try:
        canonical = str(UUID(version_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid Worker version UUID") from exc
    if canonical != version_id:
        raise ValueError("Worker version must be a canonical lowercase UUID")
    return {
        "strategy": "percentage",
        "versions": [{"version_id": canonical, "percentage": 100}],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = make_payload(args.version_id)
        # Atomic exclusive creation: never overwrite an existing rollback payload
        # and never emit its body into GitHub Action logs.
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
    except (ValueError, FileExistsError, OSError) as exc:
        print("B62_ROLLBACK_REQUEST=BLOCKED:" + type(exc).__name__)
        return 1
    print("B62_ROLLBACK_REQUEST=VALIDATED")
    print("ROLLBACK_BODY_SECRETS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
