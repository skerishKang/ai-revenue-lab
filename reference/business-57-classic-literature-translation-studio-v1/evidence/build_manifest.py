#!/usr/bin/env python3
"""Build SHA-256/size/dimension evidence manifest for Business 57."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
OUT = EVIDENCE / "evidence-manifest.json"
RUNTIME = [
    "index.html",
    "styles/main.css",
    "scripts/review.js",
    "assets/rose-mark.svg",
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def record(path: Path) -> dict[str, object]:
    item: dict[str, object] = {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
    }
    if path.suffix.lower() in {".png", ".gif"}:
        with Image.open(path) as image:
            item["width"] = image.width
            item["height"] = image.height
            item["frames"] = getattr(image, "n_frames", 1)
    return item


def main() -> None:
    evidence_files = [
        EVIDENCE / "validation.json",
        EVIDENCE / "browser-validation.json",
        *sorted((EVIDENCE / "screenshots").glob("*")),
    ]
    payload = {
        "business": 57,
        "slug": "classic-literature-translation-studio",
        "generated_at": "2026-07-28",
        "starting_remote_head": "c5ee696a6dcef346f28e487777b0f7068b22094c",
        "evidence_source_head": os.environ.get("EVIDENCE_SOURCE_HEAD", "PENDING_REMOTE_SOURCE_COMMIT"),
        "final_head_record": "The final PR head is recorded in the PR body after the manifest commit; runtime byte hashes below remain authoritative.",
        "runtime": [record(ROOT / item) for item in RUNTIME],
        "evidence": [record(path) for path in evidence_files if path.is_file()],
        "drive": {
            "folder_url": os.environ.get("DRIVE_FOLDER_URL", "DRIVE_UPLOAD_PENDING"),
            "evidence_archive_url": os.environ.get("DRIVE_ARCHIVE_URL", "DRIVE_UPLOAD_PENDING"),
            "evidence_archive_bytes": int(os.environ.get("DRIVE_ARCHIVE_BYTES", "0")),
            "evidence_archive_sha256": os.environ.get("DRIVE_ARCHIVE_SHA256", "DRIVE_UPLOAD_PENDING"),
            "source_archive_url": os.environ.get("DRIVE_SOURCE_URL", "DRIVE_UPLOAD_PENDING"),
            "source_archive_bytes": int(os.environ.get("DRIVE_SOURCE_BYTES", "0")),
            "source_archive_sha256": os.environ.get("DRIVE_SOURCE_SHA256", "DRIVE_UPLOAD_PENDING"),
            "download_readback": os.environ.get("DRIVE_READBACK", "PENDING"),
            "zip_integrity": os.environ.get("ZIP_INTEGRITY", "PENDING"),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
