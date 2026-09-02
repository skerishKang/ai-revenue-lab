#!/usr/bin/env python3
"""Generate B35 customer package generation manifest with revision trace and hashes.

Required fields per #1504:
  SOURCE_REVISION
  PRODUCT_AUTHORITY_REVISION
  GENERATOR_REVISION
  OUTPUT_FILE_LIST
  OUTPUT_HASHES
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path
import datetime

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(__file__).resolve().parents[5] if (Path(__file__).resolve().parents[5] / ".git").exists() else Path(__file__).resolve().parent.parent.parent.parent.parent
# fallback to repo root discovery
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

def git_rev(path: str = "") -> str:
    try:
        if path:
            out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True)
            return out.stdout.strip()
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        return out.stdout.strip()
    except Exception:
        return "unknown"

def git_file_hash(rel: str) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", f"HEAD:{rel}"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        return out.stdout.strip() or "uncommitted"
    except Exception:
        return "unknown"

def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    # Determine revisions
    try:
        base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True).stdout.strip()
    except Exception:
        base_sha = "unknown"
    # Product authority revision: hash of PRODUCT_CONTRACT.md file
    product_path = REPO_ROOT / "reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md"
    if product_path.exists():
        product_rev = git_file_hash("reference/business-35-ai-media-education-dx-v3/PRODUCT_CONTRACT.md")
        if not product_rev or product_rev == "uncommitted":
            product_rev = file_sha256(product_path)[:12]
    else:
        product_rev = "missing"

    # Generator revision: hash of builder scripts
    builder_files = sorted((ROOT / "validation").glob("build_*.py"))
    gen_hash = hashlib.sha256()
    for bf in builder_files:
        gen_hash.update(bf.read_bytes())
    generator_rev = gen_hash.hexdigest()[:12]

    # Source revision: Lane A branch not yet accepted. Record pending + current product rev
    # Per #1504, final binaries must use accepted #1503 exact head. Until then, mark PENDING.
    source_rev = "PENDING_ACCEPTED_1503"
    # Try to detect Lane A branch head if exists
    try:
        out = subprocess.run(["git", "rev-parse", "origin/feat/b35-w1-commercial-source-v31"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        lane_a_head = out.stdout.strip()
        if lane_a_head:
            source_rev = f"PENDING_ACCEPTED_1503_LANE_A_HEAD_{lane_a_head[:12]}"
    except Exception:
        pass

    # Collect outputs
    output_list = []
    hashes = {}
    for name in OUTPUTS:
        f = ROOT / name
        if f.exists():
            output_list.append(name)
            hashes[name] = file_sha256(f)
        else:
            hashes[name] = "MISSING"
    # Also include rendered evidence if present
    for sub in ["rendered", "xlsx-rendered"]:
        for p in sorted((ROOT / sub).glob("*.png")):
            rel = f"{sub}/{p.name}"
            output_list.append(rel)
            hashes[rel] = file_sha256(p)

    output_list = sorted(set(output_list))

    manifest = {
        "SOURCE_REVISION": source_rev,
        "PRODUCT_AUTHORITY_REVISION": product_rev,
        "GENERATOR_REVISION": generator_rev,
        "BASE_SHA": base_sha,
        "GENERATED_AT": datetime.datetime(2026, 9, 3, 0, 0, 0).isoformat() + "Z",
        "OUTPUT_FILE_LIST": output_list,
        "OUTPUT_HASHES": hashes,
        "NOTES": "PRE_V3_1 historical binaries are STALE_FOR_SEND. This manifest records current deterministic build infrastructure. Final V3.1 binaries must be regenerated from accepted #1503 exact source revision.",
        "BUILD_INFRASTRUCTURE": "Lane B parallel-safe: deterministic builders, fixed timestamps, path-robust, manifest/hashes",
        "DEPENDENCY": "FINAL_SOURCE_DEPENDENCY = accepted exact head from #1503 (pending)",
    }

    out_json = ROOT / "GENERATION_MANIFEST.json"
    out_md = ROOT / "GENERATION_MANIFEST.md"

    out_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    md_lines = [
        "# B35 Generation Manifest",
        "",
        "```text",
        f"SOURCE_REVISION={manifest['SOURCE_REVISION']}",
        f"PRODUCT_AUTHORITY_REVISION={manifest['PRODUCT_AUTHORITY_REVISION']}",
        f"GENERATOR_REVISION={manifest['GENERATOR_REVISION']}",
        f"BASE_SHA={manifest['BASE_SHA']}",
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
    print(f"  SOURCE_REVISION={source_rev}")
    print(f"  PRODUCT_AUTHORITY_REVISION={product_rev}")
    print(f"  GENERATOR_REVISION={generator_rev}")
    print(f"  files: {len(output_list)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
