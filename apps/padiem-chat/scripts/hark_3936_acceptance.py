#!/usr/bin/env python3
"""#3936 read-only, repeatable Hark 8-scene evidence inventory.

Never sends credentials or user files anywhere; JSON contains no local paths.
Passing offline fixture checks is NEVER a claim of real Production E2E.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
from app.hark_3936_acceptance import (  # noqa: E402
    SCENES, Hark3936EvidenceError,
    acceptance_matrix, verify_synthetic_quote_pair,
)


def private_reference_ids(folder: Path | None) -> set[str]:
    if folder is None or not folder.is_dir():
        return set()
    # Only names and nonempty file metadata; no pixel/cookie/PII is ingested.
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".png"]
    ids = set()
    for idx, scene in enumerate(SCENES, 1):
        matching = [p for p in files if p.name.startswith(f"{idx:02d}_") and p.stat().st_size > 0]
        if len(matching) == 1:
            ids.add(scene)
    return ids


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reference-dir", type=Path)
    p.add_argument("--original-xlsx", type=Path)
    p.add_argument("--updated-xlsx", type=Path)
    p.add_argument("--original-sha256")
    p.add_argument("--output", type=Path)
    p.add_argument("--tested-scenes", nargs="*", choices=SCENES, default=())
    a = p.parse_args()
    status = None
    fixture_error = None
    provided = (a.original_xlsx, a.updated_xlsx, a.original_sha256)
    if any(x is not None for x in provided):
        if not all(x is not None for x in provided):
            fixture_error = "XLSX_EVIDENCE_SET_INCOMPLETE"
        else:
            try:
                original = a.original_xlsx.read_bytes()
                updated = a.updated_xlsx.read_bytes()
                status = verify_synthetic_quote_pair(
                    original=original, updated=updated, recorded_original_sha256=a.original_sha256
                )
            except (OSError, Hark3936EvidenceError) as exc:
                fixture_error = exc.args[0] if isinstance(exc, Hark3936EvidenceError) else "XLSX_EVIDENCE_NOT_READABLE"
    matrix = acceptance_matrix(
        supported_component_scenes=set(a.tested_scenes),
        private_reference_scenes=private_reference_ids(a.reference_dir),
        synthetic_fixture_checked=status is not None,
    )
    # The computed SHA evidence may be logged, but NEVER original / edited file paths.
    matrix["synthetic_quote_fixture"] = status if status is not None else {"status": "NOT_PROVEN"}
    if fixture_error:
        matrix["blockers"].append(fixture_error)
    # Real screenshots/private reference files are never opened, copied or published.
    result = json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if a.output:
        # Guard against overwriting private baseline input or a previous report.
        try:
            with a.output.open("x", encoding="utf-8") as target:
                target.write(result)
        except FileExistsError:
            print("HARK_3936_REPORT=EXISTS_FAIL_CLOSED", file=sys.stderr)
            return 2
    else:
        print(result, end="")
    print("HARK_3936_STATUS=BLOCKED_REAL_E2E", file=sys.stderr)
    return 0 if fixture_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
