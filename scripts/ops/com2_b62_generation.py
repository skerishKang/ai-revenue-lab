#!/usr/bin/env python3
"""Read-only verification of the COM2 B62 generation pointer.

The runtime consumes ``generation-store/current_generation.json`` to select the
active Chat D1 seed and R2 generation (see ``b62_generation_binding``). This
operator tool checks the same pointer independently: the seed size, SHA-256 and
table count must match, and the R2 staging pointer must name the generation
whose manifest exists on disk.

Nothing is written, copied or repaired. A missing or inconsistent generation
fails closed with a stable code so an operator can stop before the runtime
opens an older or partial dataset.

Usage:
    python scripts/ops/com2_b62_generation.py verify
    python scripts/ops/com2_b62_generation.py verify \\
        --store D:/PADIEM-Servers/b62-chat-api/runtime/generation-store --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, Sequence

POINTER_KIND = "PADIEM_COM2_B62_GENERATION_V1"
DEFAULT_STORE = Path(r"D:\PADIEM-Servers\b62-chat-api\runtime\generation-store")
DEFAULT_R2_ROOT = Path(r"D:\PADIEM-Servers\infrastructure\storage-migration\r2-staging")

_SEED_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.sqlite3"
_GENERATION = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_SHA256 = r"[a-f0-9]{64}"


class GenerationError(Exception):
    """The pointer cannot be trusted. The message is a stable code."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GenerationError(code) from error


def _safe_name(value: Any, pattern: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if Path(value).name != value or "\\" in value or "/" in value:
        return False
    return re.fullmatch(pattern, value) is not None


def load_pointer(store: Path) -> dict[str, Any]:
    path = Path(store) / "current_generation.json"
    if not path.is_file():
        raise GenerationError("b62_generation_pointer_missing")
    pointer = _read_json(path, "b62_generation_pointer_invalid")
    if not isinstance(pointer, dict) or pointer.get("kind") != POINTER_KIND:
        raise GenerationError("b62_generation_pointer_invalid")
    if pointer.get("production_bound") is not False:
        raise GenerationError("b62_generation_production_bound")
    if not _safe_name(pointer.get("d1_seed"), _SEED_NAME):
        raise GenerationError("b62_generation_pointer_invalid")
    size = pointer.get("d1_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise GenerationError("b62_generation_pointer_invalid")
    sha = pointer.get("d1_sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise GenerationError("b62_generation_pointer_invalid")
    if not _safe_name(pointer.get("r2_generation"), _GENERATION):
        raise GenerationError("b62_generation_pointer_invalid")
    tables = pointer.get("d1_tables")
    if tables is not None and (isinstance(tables, bool) or not isinstance(tables, int) or tables <= 0):
        raise GenerationError("b62_generation_pointer_invalid")
    return pointer


def _table_count(path: Path) -> int:
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()
    except sqlite3.Error as error:
        raise GenerationError("b62_generation_seed_unreadable") from error
    return int(row[0]) if row else 0


def verify_seed(store: Path, pointer: dict[str, Any]) -> Path:
    seed = Path(store) / pointer["d1_seed"]
    if not seed.is_file():
        raise GenerationError("b62_generation_seed_missing")
    if seed.stat().st_size != pointer["d1_bytes"] or _sha256(seed) != pointer["d1_sha256"]:
        raise GenerationError("b62_generation_seed_integrity_failed")
    expected = pointer.get("d1_tables")
    if expected is not None and _table_count(seed) != expected:
        raise GenerationError("b62_generation_seed_table_mismatch")
    return seed


def verify_r2(root: Path, generation: str) -> Path:
    root = Path(root)
    pointer_path = root / "current_generation.json"
    if not pointer_path.is_file():
        raise GenerationError("r2_generation_pointer_missing")
    pointer = _read_json(pointer_path, "r2_generation_pointer_invalid")
    if not isinstance(pointer, dict) or pointer.get("generation") != generation:
        raise GenerationError("r2_generation_pointer_mismatch")
    if pointer.get("production_bound") is not False:
        raise GenerationError("r2_generation_production_bound")
    if not (root / "generations" / generation / "manifest.json").is_file():
        raise GenerationError("r2_staging_generation_unavailable")
    return root


def verify_generation(store: Path, r2_root: Path | None = None) -> dict[str, Any]:
    store = Path(store)
    pointer = load_pointer(store)
    seed = verify_seed(store, pointer)
    root = Path(r2_root) if r2_root else Path(pointer.get("r2_root") or DEFAULT_R2_ROOT)
    verify_r2(root, pointer["r2_generation"])
    return {
        "kind": pointer["kind"],
        "d1_generation": pointer.get("d1_generation"),
        "d1_seed": seed.name,
        "d1_bytes": pointer["d1_bytes"],
        "d1_sha256": pointer["d1_sha256"],
        "d1_tables": pointer.get("d1_tables"),
        "r2_generation": pointer["r2_generation"],
        "production_bound": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="check the pointer and both artifacts")
    verify.add_argument("--store", default=str(DEFAULT_STORE))
    verify.add_argument("--r2-root", default=None)
    verify.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = verify_generation(Path(args.store), Path(args.r2_root) if args.r2_root else None)
    except GenerationError as error:
        print(f"B62_GENERATION_FAILED reason={error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            "B62_GENERATION_OK "
            f"d1_generation={summary['d1_generation']} d1_seed={summary['d1_seed']} "
            f"d1_bytes={summary['d1_bytes']} d1_sha256={summary['d1_sha256']} "
            f"d1_tables={summary['d1_tables']} r2_generation={summary['r2_generation']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
