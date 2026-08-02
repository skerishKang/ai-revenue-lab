from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    ROOT / "README.md",
    ROOT / "PRODUCT_CONTRACT.md",
    ROOT / "REFERENCE_NOTES.md",
    ROOT / "index.html",
    ROOT / "styles" / "main.css",
    ROOT / "scripts" / "app.js",
]

REQUIRED_HTML = [
    "한국형 AI 코드 에이전트",
    "PERSONAL AGENT WORKBENCH",
    "Business 14 연결",
    "자동 선택 · Business 14",
    "NO SAFE ROUTE",
    "NO LIVE MODEL · NO REPOSITORY MUTATION",
    'data-start',
    'data-next',
    'data-previous',
    'data-review-decision',
    'data-mobile-view="repo"',
    'data-mobile-view="work"',
    'data-mobile-view="route"',
]

REQUIRED_JS = [
    "const steps = [",
    "function renderStep",
    "function updateRoute",
    "function selectMobilePanel",
    "replaceChildren",
    'decision === "accept"',
    'decision === "revise"',
    'decision === "reject"',
]

FORBIDDEN_RUNTIME = [
    "https://",
    "http://",
    "fetch(",
    "XMLHttpRequest",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "document.cookie",
    "innerHTML",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    assert not missing, f"missing files: {missing}"

    html = read(ROOT / "index.html")
    css = read(ROOT / "styles" / "main.css")
    js = read(ROOT / "scripts" / "app.js")

    for token in REQUIRED_HTML:
        assert token in html, f"index.html missing required token: {token}"

    for token in REQUIRED_JS:
        assert token in js, f"app.js missing required token: {token}"

    runtime = "\n".join([html, css, js])
    for token in FORBIDDEN_RUNTIME:
        assert token not in runtime, f"forbidden runtime token: {token}"

    timeline_steps = re.findall(r'data-timeline-step="(\d+)"', html)
    assert timeline_steps == [str(number) for number in range(1, 9)], timeline_steps

    evidence_tabs = re.findall(r'data-evidence-tab="([a-z]+)"', html)
    evidence_panels = re.findall(r'data-evidence-panel="([a-z]+)"', html)
    assert evidence_tabs == ["plan", "diff", "test"], evidence_tabs
    assert evidence_panels == ["plan", "diff", "test"], evidence_panels

    tab_controls = re.findall(r'aria-controls="(panel-[a-z]+)"', html)
    panel_labels = re.findall(r'aria-labelledby="(tab-[a-z]+)"', html)
    assert tab_controls == ["panel-plan", "panel-diff", "panel-test"], tab_controls
    assert panel_labels == ["tab-plan", "tab-diff", "tab-test"], panel_labels

    assert "@media(max-width:760px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert "overflow-x:hidden" in css

    assert "live model" in read(ROOT / "README.md").lower()
    assert "Business 14" in read(ROOT / "PRODUCT_CONTRACT.md")
    assert "OpenCode" in read(ROOT / "REFERENCE_NOTES.md")
    assert "OpenRouter" in read(ROOT / "REFERENCE_NOTES.md")
    assert "Cursor" in read(ROOT / "REFERENCE_NOTES.md")

    print("BUSINESS_54_CODE_AGENT_STATIC_CONTRACT_PASS")
    print("timeline_steps=8")
    print("evidence_tabs=3")
    print("external_runtime_requests=0")
    print("live_model_calls=0")
    print("real_repository_mutation=0")


if __name__ == "__main__":
    main()
