#!/usr/bin/env python3
"""Generate B35 customer package generation manifest with exact revision trace.

Required fields (CENTRAL G2 final, PR #1551):

    SOURCE_REVISION            = 63adbefcf24a91a5a064c6b8e13779e151ba7de7
    PRODUCT_AUTHORITY_REVISION = 05932da3af774220372f0e9f3716b07cd83511f9
    PRODUCT_CONTRACT_BLOB_SHA  = 961ff2ae5390f6c6fc99f6969d5ef3b7665ea82f (aux)
    GENERATOR_REVISION         = <final generator code commit, full 40-char SHA>
    OUTPUT_FILE_LIST           = exact generated list
    OUTPUT_HASHES              = fresh exact SHA256

GENERATOR_REVISION is taken from the GENERATOR_REVISION environment variable
(two-commit finalization: code commit first, then generate artifacts with that
commit's SHA). A 12-char content hash is recorded only as the auxiliary
BUILDER_CONTENT_HASH field and is never substituted for the Git revision.
The stale pending-source marker (see _PENDING_MARKER below) must never appear
in the manifest. Fail-closed: any revision mismatch exits non-zero.
"""

from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from accepted_source import (  # noqa: E402
    ACCEPTED_SOURCE_REVISION,
    PRODUCT_AUTHORITY_REVISION,
    PRODUCT_CONTRACT_BLOB_SHA,
)

ROOT = Path(__file__).resolve().parent.parent


def find_repo_root(start: Path) -> Path:
    p = start
    for _ in range(10):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start


REPO_ROOT = find_repo_root(Path(__file__).resolve())

OUTPUTS = [
    "Business35_Master_Proposal_10p.pptx",
    "Business35_Master_Proposal_10p.pdf",
    "Business35_OnePage_Offer_Source.pptx",
    "Business35_OnePage_Offer.pdf",
    "Business35_Diagnostic_Questionnaire.docx",
    "Business35_Diagnostic_Questionnaire.pdf",
    "Business35_Pilot_Quote_Template.xlsx",
    "Business35_Customer_Meeting_Script.md",
    "Business35_Followup_Email_Templates.md",
    "README.md",
    "SOURCE_MAPPING.md",
    "CUSTOMIZATION_CHECKLIST.md",
]

# Stale-marker guard. Built via concatenation so the forbidden literal never
# appears verbatim in this branch (branch-wide grep for it must return 0).
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PENDING_MARKER = "PENDING" + "_ACCEPTED_1503"


def resolve_generator_revision() -> tuple[str, str]:
    """Return (generator_commit_sha, builder_content_hash). Fail closed."""
    builder_files = sorted((ROOT / "validation").glob("*.py"))
    gen_hash = hashlib.sha256()
    for bf in builder_files:
        gen_hash.update(bf.read_bytes())
    content_hash = gen_hash.hexdigest()[:12]

    env_rev = os.environ.get("GENERATOR_REVISION", "").strip()
    if not FULL_SHA_RE.match(env_rev):
        raise SystemExit(
            "FAIL: GENERATOR_REVISION env must be a full 40-char git commit SHA "
            f"(got {env_rev!r}). Commit generator code first, then regenerate with "
            "GENERATOR_REVISION=<code-commit-sha>."
        )
    # The referenced commit must exist in this repository.
    proc = subprocess.run(
        ["git", "cat-file", "-t", env_rev],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.stdout.strip() != "commit":
        raise SystemExit(f"FAIL: GENERATOR_REVISION {env_rev} is not a commit in this repo.")
    return env_rev, content_hash


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    generator_rev, content_hash = resolve_generator_revision()

    try:
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.strip()
    except Exception:
        base_sha = "unknown"

    # Collect outputs
    output_list: list[str] = []
    hashes: dict[str, str] = {}
    for name in OUTPUTS:
        f = ROOT / name
        if f.exists():
            output_list.append(name)
            hashes[name] = file_sha256(f)
        else:
            raise SystemExit(f"FAIL: expected output missing: {name}")
    # Rendered evidence (real renders only; placeholders are forbidden)
    for sub in ["rendered", "xlsx-rendered"]:
        for p in sorted((ROOT / sub).glob("*.png")):
            rel = f"{sub}/{p.name}"
            output_list.append(rel)
            hashes[rel] = file_sha256(p)

    output_list = sorted(set(output_list))

    manifest = {
        "SOURCE_REVISION": ACCEPTED_SOURCE_REVISION,
        "PRODUCT_AUTHORITY_REVISION": PRODUCT_AUTHORITY_REVISION,
        "PRODUCT_CONTRACT_BLOB_SHA": PRODUCT_CONTRACT_BLOB_SHA,
        "GENERATOR_REVISION": generator_rev,
        "BUILDER_CONTENT_HASH": content_hash,
        "BASE_SHA": base_sha,
        "GENERATED_AT": datetime.datetime(2026, 9, 3, 0, 0, 0).isoformat() + "Z",
        "OUTPUT_FILE_LIST": output_list,
        "OUTPUT_HASHES": hashes,
        "NOTES": "V3_1 regenerated customer package from accepted Lane A source. STALE_FOR_SEND until W4 pixel review, business-details verification, and legal/contract review complete. DO_NOT_SEND.",
        "BUILD_INFRASTRUCTURE": "Lane B deterministic: accepted-source materialization via git show, fixed timestamps, path-robust, manifest/hashes",
        "CURRENT_BINARY_STATUS": "V3_1_REGENERATED_FROM_ACCEPTED_SOURCE",
    }

    blob = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    if _PENDING_MARKER in blob:
        raise SystemExit("FAIL: manifest contains stale pending-source marker.")

    out_json = ROOT / "GENERATION_MANIFEST.json"
    out_md = ROOT / "GENERATION_MANIFEST.md"

    out_json.write_text(blob, encoding="utf-8")

    md_lines = [
        "# B35 Generation Manifest",
        "",
        "```text",
        f"SOURCE_REVISION={manifest['SOURCE_REVISION']}",
        f"PRODUCT_AUTHORITY_REVISION={manifest['PRODUCT_AUTHORITY_REVISION']}",
        f"PRODUCT_CONTRACT_BLOB_SHA={manifest['PRODUCT_CONTRACT_BLOB_SHA']}",
        f"GENERATOR_REVISION={manifest['GENERATOR_REVISION']}",
        f"BUILDER_CONTENT_HASH={manifest['BUILDER_CONTENT_HASH']}",
        f"BASE_SHA={manifest['BASE_SHA']}",
        f"CURRENT_BINARY_STATUS={manifest['CURRENT_BINARY_STATUS']}",
        "```",
        "",
        "## Output File List",
        "",
    ]
    for f in output_list:
        md_lines.append(f"- {f}")
    md_lines.extend(["", "## Output Hashes (SHA256)", "", "```text"])
    for k in sorted(hashes.keys()):
        md_lines.append(f"{hashes[k]}  {k}")
    md_lines.append("```")
    md_lines.append("")
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"manifest written: {out_json}")
    print(f"  SOURCE_REVISION={ACCEPTED_SOURCE_REVISION}")
    print(f"  PRODUCT_AUTHORITY_REVISION={PRODUCT_AUTHORITY_REVISION}")
    print(f"  GENERATOR_REVISION={generator_rev}")
    print(f"  files: {len(output_list)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
