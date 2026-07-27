#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
STATES = ["cover", "sources", "spine", "suite", "adaptation", "trace", "mobile"]
RUNTIME_FILES = [ROOT / "index.html", ROOT / "styles.css", ROOT / "styles-editions.css", ROOT / "styles-responsive.css", ROOT / "app.js", *sorted((ROOT / "states").glob("*.js"))]


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
    css = (ROOT / "styles.css").read_text(encoding="utf-8") + "\n" + (ROOT / "styles-editions.css").read_text(encoding="utf-8") + "\n" + (ROOT / "styles-responsive.css").read_text(encoding="utf-8")
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
            host = urlparse(url).hostname
            if host:
                external_runtime.append(f"{path.name}:{url}")
    checks.append(result("no runtime external URL", not external_runtime, f"external={external_runtime}"))

    checks.append(result("keyboard tab pattern", all(token in js for token in ["ArrowRight", "ArrowLeft", "Home", "End"]), "arrow/home/end handlers present"))
    checks.append(result("visible focus style", ":focus-visible" in css and "outline" in css, "focus-visible outline declared"))
    checks.append(result("reduced motion", "prefers-reduced-motion" in css, "reduced motion media query present"))
    checks.append(result("synthetic labels", html.count("합성") >= 10 and "SYNTHETIC" in html, f"Korean labels={html.count('합성')}"))
    checks.append(result("UI_ONLY limitations", "업로드·생성·편집·저장·내보내기·게시 기능은 구현되지 않았습니다" in html, "phase limitation visible"))
    checks.append(result("relay completion hook", "dataset.motionState" in js and "complete" in js, "motion completion marker present"))
    checks.append(result("focus preservation", "preventScroll" in js and "document.activeElement" in js, "replay focus preservation present"))
    checks.append(result("scroll preservation", "window.scrollX" in js and "window.scrollY" in js, "replay scroll preservation present"))

    report = {
        "kind": "business-22-static-contract",
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "static-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
