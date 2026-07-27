#!/usr/bin/env python3
"""Static contract checks for the Business 57 Phase 1 visual reference."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "classic-literature-translation-20260727-1"
EXPECTED_STATES = {
    "library",
    "fidelity",
    "comparison",
    "ledger",
    "poetry",
    "mobile",
    "weave",
}


def record(results: list[dict[str, object]], name: str, passed: bool, detail: str) -> None:
    results.append({"name": name, "passed": passed, "detail": detail})


def main() -> int:
    results: list[dict[str, object]] = []
    required = [
        ROOT / "index.html",
        ROOT / "styles/main.css",
        ROOT / "scripts/review.js",
        ROOT / "assets/rose-mark.svg",
        ROOT / "README.md",
        ROOT / "REFERENCE_NOTES.md",
        ROOT / "RIGHTS_AND_SOURCES.md",
        ROOT / "MOTION_SPEC.md",
    ]

    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    record(results, "required_files", not missing, "missing: " + ", ".join(missing) if missing else "all required files exist")

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "styles/main.css").read_text(encoding="utf-8")
    js = (ROOT / "scripts/review.js").read_text(encoding="utf-8")
    rights = (ROOT / "RIGHTS_AND_SOURCES.md").read_text(encoding="utf-8")

    states = set(re.findall(r'data-state="([a-z-]+)"', html))
    record(results, "seven_states", states == EXPECTED_STATES, f"found {sorted(states)}")

    targets = set(re.findall(r'data-state-target="([a-z-]+)"', html))
    record(results, "seven_controls", targets == EXPECTED_STATES, f"found {sorted(targets)}")

    versioned_css = f"main.css?v={VERSION}" in html
    versioned_js = f"review.js?v={VERSION}" in html
    record(results, "deterministic_asset_version", versioned_css and versioned_js, VERSION)

    external_runtime = re.findall(r'(?:src|href)="https?://[^"]+"', html)
    record(results, "no_external_runtime_assets", not external_runtime, f"found {external_runtime}" if external_runtime else "none")

    forbidden = [
        "이문열 문체",
        "무라카미 하루키처럼",
        "김은희 작가 스타일",
        "living author corpus included",
    ]
    hits = [term for term in forbidden if term.lower() in html.lower()]
    record(results, "no_named_living_author_mode", not hits, f"hits: {hits}" if hits else "none")

    disclosures = [
        "실제 번역 서비스·학습 모델·작가 계약이 아닙니다",
        "생존 작가 자료 없음",
        "신규 작성 한국어 데모",
        "퍼블릭도메인",
    ]
    missing_disclosures = [term for term in disclosures if term not in html]
    record(results, "required_disclosures", not missing_disclosures, f"missing: {missing_disclosures}" if missing_disclosures else "all present")

    rights_terms = [
        "public-domain original does not automatically",
        "no living-author corpus",
        "Frankenstein",
        "The Sick Rose",
        "shared-model training permission, default off",
    ]
    missing_rights = [term for term in rights_terms if term.lower() not in rights.lower()]
    record(results, "rights_manifest", not missing_rights, f"missing: {missing_rights}" if missing_rights else "rights boundary present")

    motion_terms = ["680ms", "stroke-dashoffset", "prefers-reduced-motion", "is-replaying"]
    combined_motion = css + js
    missing_motion = [term for term in motion_terms if term not in combined_motion]
    record(results, "motion_contract", not missing_motion, f"missing: {missing_motion}" if missing_motion else "motion markers present")

    lang_en = html.count('lang="en"')
    record(results, "source_language_attributes", lang_en >= 3, f"lang=en count: {lang_en}")

    aria_current = 'aria-current="page"' in html and "setAttribute('aria-current', 'page')" in js
    record(results, "review_accessibility", aria_current, "tab current-state semantics")

    passed = all(bool(item["passed"]) for item in results)
    report = {
        "business": 57,
        "slug": "classic-literature-translation-studio",
        "phase": "UI_ONLY",
        "status": "STATIC_CONTRACT_PASS" if passed else "STATIC_CONTRACT_FAIL",
        "version": VERSION,
        "checks": results,
    }

    output = ROOT / "evidence/validation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
