#!/usr/bin/env python3
"""Publish the COM2 B62 runtime generation pointer.

The COM2 B62 runtime reads exactly one pointer,
``<generation-store>/current_generation.json``, and refuses to start when the
named seed, its SHA-256, its table count or the R2 staging pointer disagree
(see ``b62_generation_binding`` on the COM2 host and
``scripts/ops/com2_b62_generation.py`` for the read-only operator check).

Nothing published the pointer after a successful D1/R2 sync, so the runtime
kept serving the generation that was published on 2026-10-19 while the sync
published a new one every day. This tool closes that gap: it prepares the
writable Chat seed for the **currently published** D1 generation and publishes
the pointer that names it together with the **currently published** R2
generation.

Safety properties:

* The immutable published generation is never modified. The runtime seed is a
  copy inside the COM2 writable Chat database, written to a temporary name,
  compared by SHA-256 against the source, integrity-checked, and only then
  moved into place.
* An existing seed for the same generation is verified, not overwritten.
* The pointer is written atomically and only after the seed is in place, so a
  reader never sees a pointer that names a missing or partial seed.
* The pointer keeps ``production_bound=false``. This tool never binds
  production; it only selects which local generation the COM2 runtime opens.
* The previous pointer is kept next to the new one so a rollback does not need
  a regeneration.

Usage:
    python scripts/ops/com2_b62_generation_publish.py publish \\
        --source-root D:/PADIEM-Servers/infrastructure/storage-migration \\
        --store D:/PADIEM-Servers/b62-chat-api/runtime/generation-store
    python scripts/ops/com2_b62_generation_publish.py publish --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

POINTER_KIND = "PADIEM_COM2_B62_GENERATION_V1"
DEFAULT_SOURCE_ROOT = Path(r"D:\PADIEM-Servers\infrastructure\storage-migration")
DEFAULT_STORE = Path(r"D:\PADIEM-Servers\b62-chat-api\runtime\generation-store")
POINTER_NAME = "current_generation.json"

_GENERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SEED_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.sqlite3\Z")


class PublishError(RuntimeError):
    """The pointer cannot be published. The message is a stable code."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublishError(code) from error


def _table_count(path: Path) -> int:
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
    except sqlite3.Error as error:
        raise PublishError("b62_generation_seed_unreadable") from error
    return int(row[0]) if row else 0


def _integrity(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
            return db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.Error:
        return False


def published_d1_generation(source_root: Path) -> dict[str, Any]:
    """Read the D1 generation the sync published."""
    pointer = _read_json(Path(source_root) / "snapshots" / POINTER_NAME, "b62_d1_pointer_missing")
    if not isinstance(pointer, dict):
        raise PublishError("b62_d1_pointer_invalid")
    generation = pointer.get("generation")
    if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
        raise PublishError("b62_d1_pointer_invalid")
    databases = pointer.get("databases")
    if not isinstance(databases, dict) or not isinstance(databases.get("chat"), dict):
        raise PublishError("b62_d1_pointer_invalid")
    if pointer.get("fresh_remote_export") is not True:
        raise PublishError("b62_d1_generation_not_fresh")
    if pointer.get("production_bound") is not False:
        raise PublishError("b62_d1_generation_production_bound")
    snapshot = (
        Path(source_root) / "snapshots" / "generations" / generation / "chat.sqlite3"
    )
    if not snapshot.is_file():
        raise PublishError("b62_d1_generation_snapshot_missing")
    return {
        "generation": generation,
        "snapshot": snapshot,
        "sha256": str(databases["chat"].get("sha256") or ""),
        "bytes": int(databases["chat"].get("bytes") or 0),
    }


def published_r2_generation(source_root: Path) -> dict[str, Any]:
    """Read the R2 generation the sync published."""
    root = Path(source_root) / "r2-staging"
    pointer = _read_json(root / POINTER_NAME, "r2_generation_pointer_missing")
    if not isinstance(pointer, dict):
        raise PublishError("r2_generation_pointer_invalid")
    generation = pointer.get("generation")
    if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
        raise PublishError("r2_generation_pointer_invalid")
    if pointer.get("production_bound") is not False:
        raise PublishError("r2_generation_production_bound")
    if not (root / "generations" / generation / "manifest.json").is_file():
        raise PublishError("r2_staging_generation_unavailable")
    return {"generation": generation, "root": root}


def prepare_seed(store: Path, generation: str, snapshot: Path) -> Path:
    """Copy the immutable chat snapshot into the writable COM2 seed."""
    name = "chat-" + generation + ".sqlite3"
    if not _SEED_NAME.fullmatch(name):
        raise PublishError("b62_generation_seed_invalid")
    target = Path(store) / name
    if target.is_file():
        if not _integrity(target):
            raise PublishError("b62_generation_seed_integrity_failed")
        return target
    temporary = target.with_suffix(".partial")
    temporary.unlink(missing_ok=True)
    with snapshot.open("rb") as reader, temporary.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    if _sha256(temporary) != _sha256(snapshot):
        temporary.unlink(missing_ok=True)
        raise PublishError("b62_generation_seed_copy_mismatch")
    if not _integrity(temporary):
        temporary.unlink(missing_ok=True)
        raise PublishError("b62_generation_seed_integrity_failed")
    os.replace(temporary, target)
    return target


def build_pointer(
    *,
    store: Path,
    d1: dict[str, Any],
    r2: dict[str, Any],
    seed: Path,
) -> dict[str, Any]:
    """Build the pointer the runtime consumes."""
    return {
        "kind": POINTER_KIND,
        "prepared_utc": _utc_now(),
        "d1_generation": d1["generation"],
        "d1_seed": seed.name,
        "d1_bytes": seed.stat().st_size,
        "d1_sha256": _sha256(seed),
        "d1_tables": _table_count(seed),
        "r2_generation": r2["generation"],
        "r2_root": str(Path(r2["root"])),
        "r2_write_overlay": str(Path(store) / "r2-writes"),
        "production_bound": False,
    }


def verify_pointer(store: Path, pointer: dict[str, Any]) -> None:
    """Re-check the published pointer the way the runtime checks it."""
    seed = Path(store) / pointer["d1_seed"]
    if not seed.is_file():
        raise PublishError("b62_generation_seed_missing")
    if seed.stat().st_size != pointer["d1_bytes"] or _sha256(seed) != pointer["d1_sha256"]:
        raise PublishError("b62_generation_seed_integrity_failed")
    if _table_count(seed) != pointer["d1_tables"]:
        raise PublishError("b62_generation_seed_table_mismatch")
    r2_root = Path(pointer["r2_root"])
    r2_pointer = _read_json(r2_root / POINTER_NAME, "r2_generation_pointer_missing")
    if r2_pointer.get("generation") != pointer["r2_generation"]:
        raise PublishError("r2_generation_pointer_mismatch")
    if r2_pointer.get("production_bound") is not False:
        raise PublishError("r2_generation_production_bound")
    if not (r2_root / "generations" / pointer["r2_generation"] / "manifest.json").is_file():
        raise PublishError("r2_staging_generation_unavailable")


def publish(
    *,
    source_root: Path,
    store: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_root = Path(source_root)
    store = Path(store)
    d1 = published_d1_generation(source_root)
    r2 = published_r2_generation(source_root)
    if d1["bytes"] and d1["sha256"]:
        # The published metadata must describe the snapshot that is on disk.
        if _sha256(d1["snapshot"]) != d1["sha256"]:
            raise PublishError("b62_d1_generation_snapshot_mismatch")
    if dry_run:
        return {
            "kind": POINTER_KIND,
            "d1_generation": d1["generation"],
            "r2_generation": r2["generation"],
            "published": False,
        }
    store.mkdir(parents=True, exist_ok=True)
    seed = prepare_seed(store, d1["generation"], d1["snapshot"])
    pointer = build_pointer(store=store, d1=d1, r2=r2, seed=seed)
    verify_pointer(store, pointer)
    target = store / POINTER_NAME
    if target.is_file():
        previous = target.read_text(encoding="utf-8")
        (store / (POINTER_NAME + ".previous")).write_text(previous, encoding="utf-8")
    temporary = store / (POINTER_NAME + ".next")
    temporary.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    verify_pointer(store, pointer)
    return dict(pointer, published=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish_parser = subparsers.add_parser(
        "publish", help="publish the pointer for the currently published generation"
    )
    publish_parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    publish_parser.add_argument("--store", default=str(DEFAULT_STORE))
    publish_parser.add_argument("--dry-run", action="store_true")
    publish_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = publish(
            source_root=Path(args.source_root),
            store=Path(args.store),
            dry_run=args.dry_run,
        )
    except PublishError as error:
        print(f"B62_GENERATION_PUBLISH_FAILED reason={error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            "B62_GENERATION_PUBLISHED "
            f"d1_generation={result['d1_generation']} d1_seed={result.get('d1_seed')} "
            f"d1_bytes={result.get('d1_bytes')} d1_sha256={result.get('d1_sha256')} "
            f"d1_tables={result.get('d1_tables')} r2_generation={result['r2_generation']} "
            f"published={str(result.get('published')).lower()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
