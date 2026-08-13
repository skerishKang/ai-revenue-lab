from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "README.md",
    "PRODUCT_CONTRACT.md",
    "REFERENCE_BOARD.md",
    "REFERENCE_NOTES.md",
    "IMAGE_SOURCES.md",
    "MOTION_SPEC.md",
    "index.html",
    "styles/main.css",
    "scripts/app.js",
)

REQUIRED_VIEWS = {"start", "models", "detail", "activity", "developer"}
REQUIRED_IDS = {
    "main",
    "task-input",
    "resolve-route",
    "route-canvas",
    "route-result-model",
    "route-response",
    "model-search",
    "model-list",
    "detail-run",
    "open-key-drawer",
    "key-drawer",
    "scope-popover",
    "optimize-popover",
    "toast",
}


class ReferenceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.views: set[str] = set()
        self.script_sources: list[str] = []
        self.stylesheet_links: list[str] = []
        self.images: list[str] = []
        self.nav_labels: list[str] = []
        self._in_primary_nav = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if identifier := values.get("id"):
            self.ids.add(identifier)
        if view := values.get("data-view"):
            self.views.add(view)
        if tag == "script" and (src := values.get("src")):
            self.script_sources.append(src)
        if tag == "link" and values.get("rel") == "stylesheet" and (href := values.get("href")):
            self.stylesheet_links.append(href)
        if tag == "img" and (src := values.get("src")):
            self.images.append(src)
        if tag == "nav" and "primary-nav" in (values.get("class") or "").split():
            self._in_primary_nav = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav" and self._in_primary_nav:
            self._in_primary_nav = False

    def handle_data(self, data: str) -> None:
        if self._in_primary_nav and data.strip():
            self.nav_labels.append(data.strip())


def fail(message: str) -> None:
    raise AssertionError(message)


def assert_required_files() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        fail(f"missing required files: {', '.join(missing)}")


def assert_html_contract() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    parser = ReferenceHTMLParser()
    parser.feed(html)

    if parser.views != REQUIRED_VIEWS:
        fail(f"unexpected view set: {sorted(parser.views)}")
    missing_ids = REQUIRED_IDS - parser.ids
    if missing_ids:
        fail(f"missing required ids: {sorted(missing_ids)}")

    if parser.script_sources != ["scripts/app.js"]:
        fail(f"unexpected runtime scripts: {parser.script_sources}")
    if parser.stylesheet_links != ["styles/main.css"]:
        fail(f"unexpected stylesheet links: {parser.stylesheet_links}")
    if parser.images:
        fail(f"runtime images must be documented and local; unexpected img sources: {parser.images}")

    remote_assets = [
        value
        for value in parser.script_sources + parser.stylesheet_links + parser.images
        if value.startswith(("http://", "https://", "//"))
    ]
    if remote_assets:
        fail(f"remote runtime assets are prohibited: {remote_assets}")

    expected_navigation = {"시작", "모델", "활동", "개발자"}
    actual_navigation = set(parser.nav_labels)
    if not expected_navigation.issubset(actual_navigation):
        fail(f"primary navigation incomplete: {sorted(actual_navigation)}")

    required_copy = (
        "Business 14 자동 선택",
        "Provider 키 연결",
        "NO SAFE ROUTE",
        "Route Trace",
        "b14/auto",
        "국내·로컬 우선",
    )
    for text in required_copy:
        if text not in html:
            fail(f"required product copy missing: {text}")

    prohibited_copy = (
        "Phase 0 Mock Demo",
        "Phase 3 Workspace",
        "AI로 혁신",
        "revolutionize with AI",
    )
    for text in prohibited_copy:
        if text in html:
            fail(f"prohibited legacy or generic copy present: {text}")


def assert_css_contract() -> None:
    css = (ROOT / "styles/main.css").read_text(encoding="utf-8")
    required = (
        "@media (max-width: 760px)",
        "@media (prefers-reduced-motion: reduce)",
        ".route-canvas",
        ".mobile-nav",
        ".key-drawer",
        ".model-row",
        ":focus-visible",
    )
    for token in required:
        if token not in css:
            fail(f"CSS contract token missing: {token}")

    if "url(http" in css.lower() or "@import" in css.lower():
        fail("remote CSS imports or URL assets are prohibited")
    if "purple" in css.lower() or "linear-gradient(135deg, #7" in css.lower():
        fail("generic purple-gradient direction detected")


def assert_javascript_contract() -> None:
    js = (ROOT / "scripts/app.js").read_text(encoding="utf-8")
    required = (
        "function setView",
        "function chooseRoute",
        "function previewRoute",
        "function filterModels",
        "function openKeyDrawer",
        "function closeKeyDrawer",
        "function copyText",
        'state.scope === "local" && state.preset === "korean"',
        'model: "NO SAFE ROUTE"',
        'event.key === "Escape"',
        'event.key === "Enter"',
    )
    for token in required:
        if token not in js:
            fail(f"JavaScript contract token missing: {token}")

    prohibited = (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "localStorage",
        "sessionStorage",
        "eval(",
        "document.write",
    )
    for token in prohibited:
        if token in js:
            fail(f"prohibited runtime behavior present: {token}")

    external_runtime_urls = re.findall(r"(?:src|href)\s*=\s*[\"']https?://", js, flags=re.IGNORECASE)
    if external_runtime_urls:
        fail("JavaScript creates external runtime assets")


def assert_dossier_contract() -> None:
    board = (ROOT / "REFERENCE_BOARD.md").read_text(encoding="utf-8")
    for reference in ("OpenRouter", "Vercel AI Gateway", "Cloudflare AI Gateway", "Requesty", "Linear", "Raycast", "Stripe"):
        if reference not in board:
            fail(f"reference board missing benchmark: {reference}")

    motion = (ROOT / "MOTION_SPEC.md").read_text(encoding="utf-8")
    if "Route Trace" not in motion or "prefers-reduced-motion" not in motion:
        fail("motion specification incomplete")

    image_sources = (ROOT / "IMAGE_SOURCES.md").read_text(encoding="utf-8")
    if "no photography" not in image_sources.lower() or "no runtime hotlink" not in image_sources.lower():
        fail("image source boundary incomplete")


def main() -> int:
    checks = (
        ("required files", assert_required_files),
        ("HTML product contract", assert_html_contract),
        ("CSS visual contract", assert_css_contract),
        ("JavaScript interaction contract", assert_javascript_contract),
        ("reference dossier", assert_dossier_contract),
    )

    for label, check in checks:
        check()
        print(f"PASS: {label}")

    print(f"PASS: Business 14 Visual Upgrade v2 static validation ({len(checks)}/{len(checks)})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
