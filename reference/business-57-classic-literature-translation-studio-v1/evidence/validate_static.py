#!/usr/bin/env python3
"""Static contract checks for Business 57 Phase 1."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "classic-literature-translation-20260728-2"
EXPECTED_STATES = {"library", "source-fidelity", "comparison", "ledger", "poetry", "mobile", "weave"}


def add(results: list[dict[str, object]], name: str, passed: bool, detail: str) -> None:
    results.append({"name": name, "passed": passed, "detail": detail})


def main() -> int:
    results: list[dict[str, object]] = []
    required = [
        "index.html", "styles/main.css", "scripts/review.js", "assets/rose-mark.svg",
        "README.md", "REFERENCE_NOTES.md", "RIGHTS_AND_SOURCES.md", "IMAGE_SOURCES.md",
        "MOTION_SPEC.md", "evidence/validate_browser.py", "evidence/build_manifest.py",
    ]
    missing = [path for path in required if not (ROOT / path).is_file()]
    add(results, "required_files", not missing, f"missing={missing}" if missing else "all present")

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "styles/main.css").read_text(encoding="utf-8")
    js = (ROOT / "scripts/review.js").read_text(encoding="utf-8")
    rights = (ROOT / "RIGHTS_AND_SOURCES.md").read_text(encoding="utf-8")
    images = (ROOT / "IMAGE_SOURCES.md").read_text(encoding="utf-8")
    refs = (ROOT / "REFERENCE_NOTES.md").read_text(encoding="utf-8")
    motion = (ROOT / "MOTION_SPEC.md").read_text(encoding="utf-8")

    states = set(re.findall(r'data-state="([a-z-]+)"', html))
    targets = set(re.findall(r'data-state-target="([a-z-]+)"', html))
    add(results, "seven_states", states == EXPECTED_STATES, str(sorted(states)))
    add(results, "seven_controls", targets == EXPECTED_STATES, str(sorted(targets)))

    version_ok = all(token in html for token in [f"main.css?v={VERSION}", f"review.js?v={VERSION}", VERSION])
    add(results, "deterministic_asset_version", version_ok, VERSION)

    local_refs = re.findall(r'(?:src|href)="([^"#]+)"', html)
    external = [ref for ref in local_refs if re.match(r"https?://", ref)]
    missing_assets = []
    for ref in local_refs:
        if ref.startswith(("http://", "https://")) or not ref.startswith("./"):
            continue
        clean = ref[2:].split("?", 1)[0]
        if not (ROOT / clean).is_file():
            missing_assets.append(clean)
    add(results, "no_external_runtime_assets", not external, str(external) if external else "none")
    add(results, "local_assets_exist", not missing_assets, str(missing_assets) if missing_assets else "all resolve")

    gradients = re.findall(r"(?:repeating-)?(?:linear|radial|conic)-gradient\s*\(", css, flags=re.I)
    add(results, "no_gradients", not gradients, str(gradients) if gradients else "none")

    tab_semantics = html.count('role="tab"') == 7 and html.count('role="tabpanel"') == 7
    accessible = tab_semantics and 'aria-selected="true"' in html and "tab.setAttribute('aria-selected'" in js
    add(results, "accessible_review_controls", accessible, "7 tabs + 7 tabpanels + selected state")
    add(results, "source_language_attributes", html.count('lang="en"') >= 4, f"count={html.count('lang=\"en\"')}")

    content_terms = [
        "lifeless thing", "생기 없는 것", "죽은 몸", "life → lifeless → being",
        "instruments of life", "갈바니즘", "손실", "Human review pending",
        "실제 모델·외부 코퍼스 미연결", "신규 작성", "원전 보존 번역", "현대 독해 번역",
    ]
    missing_content = [term for term in content_terms if term not in html]
    add(results, "literary_decision_content", not missing_content, f"missing={missing_content}" if missing_content else "all present")

    exact_sources = [
        "FRANKENSTEIN · 1818 EDITION · CHAPTER IV",
        "It was on a dreary night of November,",
        "O rose thou art sick.",
        "Project Gutenberg #41445",
    ]
    missing_sources = [term for term in exact_sources if term not in html + rights]
    add(results, "exact_source_fixture", not missing_sources, f"missing={missing_sources}" if missing_sources else "edition and punctuation aligned")

    rights_terms = [
        "https://www.gutenberg.org/ebooks/41445", "https://www.law.go.kr/법령/저작권법",
        "https://www.wipo.int/wipolex/en/text/283698", "2026-07-28",
        "Modern Korean translation copied: no", "Production model connected: no",
    ]
    missing_rights = [term for term in rights_terms if term not in rights]
    add(results, "rights_and_source_manifest", not missing_rights, f"missing={missing_rights}" if missing_rights else "record complete")
    add(results, "image_source_manifest", "assets/rose-mark.svg" in images and "repository-local original" in images, "local original recorded")
    add(results, "reference_urls", refs.count("https://") >= 5, f"urls={refs.count('https://')}")

    motion_ok = all(term in css + js + motion for term in [
        'data-motion-state="running"', "480ms", "380ms", "animationend", "settle-rendering",
        "Computed maximum end: 680ms",
    ]) and "setTimeout" not in js
    add(results, "motion_completion_contract", motion_ok, "computed 680ms + animationend + no fixed timeout")
    add(results, "reduced_motion_contract", "prefers-reduced-motion: reduce" in css and "reducedMotion.matches" in js, "present")

    forbidden = ["이문열 문체", "무라카미 하루키처럼", "living author corpus included"]
    corpus = (html + refs + rights).lower()
    hits = [term for term in forbidden if term.lower() in corpus]
    if re.search(r"(?<!NOT_)\bUI_APPROVED\b", html + refs + rights):
        hits.append("standalone UI_APPROVED")
    add(results, "forbidden_claims_absent", not hits, str(hits) if hits else "none")

    passed = all(bool(item["passed"]) for item in results)
    report = {
        "business": 57,
        "slug": "classic-literature-translation-studio",
        "phase": "UI_ONLY",
        "version": VERSION,
        "status": "STATIC_CONTRACT_PASS" if passed else "STATIC_CONTRACT_FAIL",
        "checks": results,
    }
    output = ROOT / "evidence/validation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
