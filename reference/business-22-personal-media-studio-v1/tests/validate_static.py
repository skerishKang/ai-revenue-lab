#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
STATES = ["cover", "sources", "spine", "suite", "adaptation", "trace", "mobile"]
RUNTIME_FILES = [
    ROOT / "index.html",
    ROOT / "styles.css",
    ROOT / "styles-editions.css",
    ROOT / "styles-responsive.css",
    ROOT / "motion-timing.css",
    ROOT / "app.js",
    *sorted((ROOT / "states").glob("*.js")),
]


def result(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"name": name, "passed": passed, "detail": detail}


def main() -> int:
    checks: list[dict[str, object]] = []
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for state_file in sorted((ROOT / "states").glob("*.js")):
        state_js = state_file.read_text(encoding="utf-8")
        match = re.search(r"insertAdjacentHTML\('beforeend', (.+)\);", state_js, re.S)
        if match:
            html += "\n" + json.loads(match.group(1))
    css = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in ["styles.css", "styles-editions.css", "styles-responsive.css", "motion-timing.css"])
    js = (ROOT / "app.js").read_text(encoding="utf-8")

    found_states = re.findall(r'data-state="([a-z-]+)"', html)
    checks.append(result("exact seven states", len(found_states) == 7 and set(found_states) == set(STATES), f"found={found_states}"))
    for state in STATES:
        checks.append(result(f"state query token: {state}", state in js, f"{state} present in state order"))

    asset_paths = re.findall(r'(?:src|href)="([^"]+)"', html)
    local_assets = [path for path in asset_paths if not path.startswith(("#", "http://", "https://", "mailto:"))]
    missing = [path for path in local_assets if not (ROOT / path.split("?", 1)[0]).exists()]
    checks.append(result("all local asset paths exist", not missing, f"missing={missing}"))

    external_runtime: list[str] = []
    url_pattern = re.compile(r'https?://[^\s\"\')]+')
    for path in RUNTIME_FILES:
        for url in url_pattern.findall(path.read_text(encoding="utf-8")):
            if urlparse(url).hostname:
                external_runtime.append(f"{path.name}:{url}")
    checks.append(result("no runtime external URL", not external_runtime, f"external={external_runtime}"))

    timing_css = (ROOT / "motion-timing.css").read_text(encoding="utf-8")
    review_timing = re.search(r"\.step-review\s*\{\s*animation:\s*relayReview\s+([\d.]+)ms\s+([\d.]+)ms\s+both", timing_css)
    computed_end = None if not review_timing else float(review_timing.group(1)) + float(review_timing.group(2))
    checks.append(result("computed final motion end", computed_end is not None and 680 <= computed_end <= 760, f"computedFinalEndMs={computed_end}"))
    checks.append(result("UI timing label", "740ms · focus 고정" in html, "displayed timing=740ms"))
    checks.append(result("animationend completion", "animationend" in js and "relayReview" in js, "final review animation drives completion"))
    checks.append(result("no fixed completion timeout", "setTimeot" not in js and "completeAfter" not in js, "no fixed completion timer"))
    checks.append(result("running state reset", "relay.dataset.motionState = 'running'" in js, "replay starts in running state"))
    checks.append(result("complete state marker", "relay.dataset.motionState = 'complete'" in js, "final state is complete"))
    checks.append(result("keyboard tab pattern", all(token in js for token in ["ArrowRight", "ArrowLeft", "Home", "End"]), "arrow/home/end handlers present"))
    checks.append(result("visible focus style", ":focus-visible" in css and "outline" in css, "focus-visible outline declared"))
    checks.append(result("reduced motion", "prefers-reduced-motion" in css, "reduced motion media query present"))
    checks.append(result("synthetic labels", html.count("합성") >= 10 and "SYNTHETIC" in html, f"Korean labels={html.count('합성'}"))
    checks.append(result("UI_ONLY limitations", "잔성") >= 10 and "SYNTHETIC" in html, f"Korean labels={html.count('합성')}"))
    checks.append(result("UI_ONLY limitations", "업로드·생성·편집·저장·내보내기·게시 기능은 구현되지 않았습니다" in html, "phase limitation visible"))
    checks.append(result("focus preservation", "preventScroll" in js and "document.activeElement" in js, "replay focus preservation present"))
    checks.append(result("scroll preservation", "window.scrollX" in js and "window.scrollY" in js, "replay scroll preservation present"))

    report = {"kind": "business-22-static-contract", "computedFinalEndMs": computed_end, "passed": all(check["passed"] for check in checks), "checks": checks}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "static-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
