#!/usr/bin/env python3
"""#4139 no-deploy Worker dry-run build fingerprint.

Hashes only local, synthetic, *already built* package bytes. This is evidence
that one Git checkout produced one dry-run output, NOT a verification of any
Cloudflare served version, a reproducible build or a signing attestation.
Never serialize build content, file paths, account IDs, secrets, or token values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

_CONTRACT = "padiem.connector-local-bundle-fingerprint.v1"
_WORKERS = frozenset({
    "padiem-control-plane-identity",
    "padiem-local-agent-broker-state",
    "padiem-local-agent-broker-edge",
})
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_SECRET_WORDS = frozenset({
    ".env", ".pem", ".key", ".p12", ".pfx", ".secrets",
    "secrets", "secret", "credentials", "token",
})
_LIMIT = 20000
_MAX_SIZE = 512 * 1024 * 1024


class FingerprintError(ValueError):
    """Fail-closed source-only validation; no raw paths in messages."""


def fingerprint(bundle_dir: Path, *, worker: str, source_sha: str) -> dict[str, object]:
    if worker not in _WORKERS or type(source_sha) is not str or not _SHA.fullmatch(source_sha):
        raise FingerprintError("unreviewed Worker name or source SHA")
    root = Path(bundle_dir)
    if root.is_symlink() or not root.is_dir():
        raise FingerprintError("bundle directory absent or symlinked")

    files: list[tuple[str, Path]] = []
    for current, folders, filenames in os.walk(root, topdown=True, followlinks=False):
        folders.sort()
        filenames.sort()
        for name in folders + filenames:
            p = Path(current) / name
            if p.is_symlink():
                raise FingerprintError("bundle contains symlink")
            if name.lower() in _SECRET_WORDS or (
                name.lower().endswith((".pem", ".key", ".p12", ".pfx", ".env"))
            ):
                raise FingerprintError("potential credential material in bundle tree")
        for name in filenames:
            path = Path(current) / name
            if not path.is_file():
                raise FingerprintError("bundle contains unsupported filesystem entry")
            relative = path.relative_to(root).as_posix()
            files.append((relative, path))
            if len(files) > _LIMIT:
                raise FingerprintError("bundle file count exceeds safe bound")
    if not files:
        raise FingerprintError("empty packaged Worker")

    h = hashlib.sha256()
    h.update(b"PADIEM-CONNECTOR-BUNDLE-FINGERPRINT\x00V1\x00")
    total = 0
    for name, path in sorted(files):
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise FingerprintError("bundle entry is not an isolated regular file")
        if before.st_size > _MAX_SIZE or total + before.st_size > _MAX_SIZE:
            raise FingerprintError("bundle exceeds safe size bound")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        after = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise FingerprintError("bundle entry changed while hashing")
        filename = name.encode("utf-8")
        h.update(len(filename).to_bytes(4, "big"))
        h.update(filename)
        h.update(before.st_size.to_bytes(8, "big"))
        h.update(digest.digest())
        total += before.st_size
    return {
        "contract": _CONTRACT,
        "worker": worker,
        "source_git_sha": source_sha,
        "dry_run_bundle_sha256": h.hexdigest(),
        "file_count": len(files),
        "total_bytes": total,
        "build_type": "synthetic_dry_run",
        "served_version_bound": False,
        "reviewed_source_to_served_bundle_attested": False,
        "production_mutation": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True, choices=sorted(_WORKERS))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        proof = fingerprint(args.bundle_dir, worker=args.worker, source_sha=args.source_sha)
        out = args.output
        if out.is_symlink() or out.exists() or out.resolve().is_relative_to(args.bundle_dir.resolve()):
            raise FingerprintError("output must be a fresh file outside bundle")
        if not out.parent.is_dir() or out.parent.is_symlink():
            raise FingerprintError("output directory not pre-created or is symlinked")
        # Exclusive create: never overwrite a previous build receipt.
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(proof, f, sort_keys=True, separators=(",", ":"))
            f.write("\n")
    except (FingerprintError, OSError, OverflowError) as exc:
        # Paths and underlying OS exception strings could contain sensitive text.
        del exc
        print("CONNECTOR_DRY_RUN_BUNDLE_FINGERPRINT=HOLD")
        print("SERVED_SOURCE_PARITY_ATTESTED=NO")
        return 1
    print("CONNECTOR_DRY_RUN_BUNDLE_FINGERPRINT=PASS")
    print("SERVED_SOURCE_PARITY_ATTESTED=NO")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
