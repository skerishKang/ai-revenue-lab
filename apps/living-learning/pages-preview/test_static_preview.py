"""Standalone acceptance tests for the Living Learning static UI preview.

These tests scan the committed ``pages-preview`` static site directly (there is
no build step — the HTML/CSS files in ``pages-preview/`` are exactly what gets
deployed to Cloudflare Pages). They verify the UI-first deployment contract:

    * every required screen is generated;
    * every internal ``href``/``src`` resolves to a real file;
    * no external CDN / external JavaScript / external stylesheet / external link;
    * no ``fetch()`` / XHR / mutation JavaScript and no ``<script>`` at all;
    * no real API URL, secret-like token, localhost, or production host;
    * no real PII (email, phone, resident-registration number);
    * every page carries the preview banner, ``noindex,nofollow`` and a viewport;
    * every page has a primary ``<h1>``;
    * form controls are labelled and no page can issue a POST (no submit control,
      no ``method="post"``);
    * no forbidden sibling-app reference is imported or linked;
    * deploy files (``_headers``/``robots.txt``/``_redirects``) exist and the
      ``_headers`` CSP forbids scripts and form submission.

The tests use only the Python standard library plus pytest. They never import
the FastAPI backend, touch a database, call a provider, or use the network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent

REQUIRED_PAGES = [
    "index.html",
    "goals/index.html",
    "diagnostic/index.html",
    "home/index.html",
    "lesson-1/index.html",
    "lesson-1/result/index.html",
    "feedback/index.html",
    "changes/index.html",
    "lesson-2/index.html",
    "progress/index.html",
    "history/index.html",
    "review/index.html",
    "review/ll-0417/index.html",
    "404.html",
]

# Pages that are app screens (everything except the marketing landing + 404).
APP_PAGES = [p for p in REQUIRED_PAGES if p not in ("index.html", "404.html")]

# Onboarding screens are a separate pre-app flow: they share the studio shell
# but are not one of the main nav sections, so they must NOT carry a (false)
# aria-current marker.
ONBOARDING_PAGES = ["goals/index.html", "diagnostic/index.html"]

# App screens that map to a sidebar nav section and therefore must mark the
# active section with aria-current="page".
NAV_PAGES = [p for p in APP_PAGES if p not in ONBOARDING_PAGES]

HREF_SRC = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"', re.IGNORECASE)
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")
RRN = re.compile(r"\d{6}-\d{7}")
API_KEY = re.compile(r"sk-[a-zA-Z0-9]{20,}|AIza[a-zA-Z0-9_-]{20,}|gh[pousr]_[a-zA-Z0-9]{20,}")
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
SIBLING_APPS = [
    "personal-edition",
    "living-travel",
    "living-fiction",
    "world-feed",
    "personal-video-archive",
    "korean-ai-platform",
]


def _pages() -> dict[str, str]:
    return {p: (BASE_DIR / p).read_text(encoding="utf-8") for p in REQUIRED_PAGES}


def _resolve(target: str) -> Path:
    """Map an absolute site path to a file under pages-preview."""
    rel = target.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    elif "." not in rel.rsplit("/", 1)[-1]:
        rel += "/index.html"
    return BASE_DIR / rel


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def test_all_required_pages_exist() -> None:
    missing = [p for p in REQUIRED_PAGES if not (BASE_DIR / p).is_file()]
    assert not missing, f"missing pages: {missing}"


def test_deploy_files_exist() -> None:
    for name in ("_headers", "robots.txt", "_redirects"):
        assert (BASE_DIR / name).is_file(), f"missing deploy file: {name}"


def test_css_assets_exist() -> None:
    for name in ("tokens.css", "base.css", "components.css", "pages.css"):
        assert (BASE_DIR / "assets" / "css" / name).is_file(), f"missing css: {name}"


# ---------------------------------------------------------------------------
# Internal links resolve
# ---------------------------------------------------------------------------
def test_internal_links_resolve() -> None:
    broken: list[str] = []
    for page, html in _pages().items():
        for target in HREF_SRC.findall(html):
            if not target.startswith("/"):
                continue
            if not _resolve(target).exists():
                broken.append(f"{page} -> {target}")
    assert not broken, f"broken internal links: {broken}"


# ---------------------------------------------------------------------------
# No external resources / requests
# ---------------------------------------------------------------------------
def test_no_external_references() -> None:
    offenders: list[str] = []
    for page, html in _pages().items():
        for target in HREF_SRC.findall(html):
            low = target.lower()
            if low.startswith(("http://", "https://", "//")) or low.startswith("mailto:"):
                offenders.append(f"{page} -> {target}")
    assert not offenders, f"external href/src found: {offenders}"


def test_no_external_cdn_or_js_keywords() -> None:
    pattern = re.compile(
        r"cdn\.|unpkg\.com|jsdelivr|googleapis|gstatic|cloudfront|bootstrap|tailwind",
        re.IGNORECASE,
    )
    offenders = [p for p, html in _pages().items() if pattern.search(html)]
    assert not offenders, f"external CDN keyword in: {offenders}"


def test_no_script_fetch_or_mutation_js() -> None:
    pattern = re.compile(
        r"<script|fetch\s*\(|XMLHttpRequest|\baxios\b|\.submit\s*\(|window\.open\s*\(",
        re.IGNORECASE,
    )
    offenders = [p for p, html in _pages().items() if pattern.search(html)]
    assert not offenders, f"script/fetch/mutation JS in: {offenders}"


def test_no_inline_event_handlers() -> None:
    offenders = [p for p, html in _pages().items() if INLINE_HANDLER.search(html)]
    assert not offenders, f"inline event handler in: {offenders}"


# ---------------------------------------------------------------------------
# No secrets / real API / PII
# ---------------------------------------------------------------------------
def test_no_real_api_or_localhost() -> None:
    pattern = re.compile(
        r"api\.openai\.com|api\.anthropic\.com|localhost|127\.0\.0\.1|0\.0\.0\.0|"
        r"https?://api\.|uvicorn|/api/v1/",
        re.IGNORECASE,
    )
    offenders = [p for p, html in _pages().items() if pattern.search(html)]
    assert not offenders, f"real API/localhost reference in: {offenders}"


def test_no_secrets() -> None:
    offenders = [p for p, html in _pages().items() if API_KEY.search(html)]
    assert not offenders, f"secret-like token in: {offenders}"


def test_no_real_pii() -> None:
    offenders: list[str] = []
    for page, html in _pages().items():
        if EMAIL.search(html) or PHONE.search(html) or RRN.search(html):
            offenders.append(page)
    assert not offenders, f"possible real PII in: {offenders}"


# ---------------------------------------------------------------------------
# No forbidden sibling-app coupling
# ---------------------------------------------------------------------------
def test_no_sibling_app_reference() -> None:
    offenders: list[str] = []
    for page, html in _pages().items():
        for app in SIBLING_APPS:
            if app in html:
                offenders.append(f"{page}: {app}")
    assert not offenders, f"sibling app reference in: {offenders}"


# ---------------------------------------------------------------------------
# Per-page contract: banner, noindex, viewport, h1
# ---------------------------------------------------------------------------
def test_preview_banner_on_every_page() -> None:
    for page, html in _pages().items():
        assert "UI Preview" in html, f"banner missing 'UI Preview' in {page}"
        assert "Synthetic learner" in html, f"banner missing 'Synthetic learner' in {page}"
        assert "No persistence" in html, f"banner missing 'No persistence' in {page}"


def test_noindex_on_every_page() -> None:
    for page, html in _pages().items():
        assert re.search(
            r'<meta\s+name="robots"\s+content="noindex,nofollow"', html
        ), f"noindex meta missing in {page}"


def test_viewport_on_every_page() -> None:
    for page, html in _pages().items():
        assert re.search(
            r'<meta\s+name="viewport"\s+content="width=device-width', html
        ), f"viewport meta missing in {page}"


def test_primary_heading_on_every_page() -> None:
    for page, html in _pages().items():
        assert re.search(r"<h1[\s>]", html), f"<h1> missing in {page}"


def test_lang_korean() -> None:
    for page, html in _pages().items():
        assert re.search(r'<html\s+lang="ko"', html), f'lang="ko" missing in {page}'


# ---------------------------------------------------------------------------
# Forms: labelled, and no POST possible
# ---------------------------------------------------------------------------
def test_form_controls_are_labelled() -> None:
    for page, html in _pages().items():
        controls = len(re.findall(r'<input\s+type="(?:radio|checkbox)"', html))
        if controls == 0:
            continue
        labels = len(re.findall(r"<label[\s>]", html))
        assert labels >= controls, (
            f"{page}: {controls} form controls but only {labels} <label> elements"
        )


def test_no_post_or_submit_controls() -> None:
    for page, html in _pages().items():
        assert not re.search(r'method\s*=\s*"post"', html, re.IGNORECASE), (
            f'{page}: method="post" found'
        )
        assert not re.search(r'type\s*=\s*"submit"', html, re.IGNORECASE), (
            f"{page}: submit control found"
        )
        assert "<button" not in html.lower(), f"{page}: <button> element found"


# ---------------------------------------------------------------------------
# Deploy file contents
# ---------------------------------------------------------------------------
def test_headers_csp_is_restrictive() -> None:
    headers = (BASE_DIR / "_headers").read_text(encoding="utf-8")
    assert "script-src 'none'" in headers, "_headers must forbid scripts"
    assert "form-action 'none'" in headers, "_headers must forbid form submission"
    assert "connect-src 'none'" in headers, "_headers must forbid network connects"
    assert "X-Robots-Tag: noindex, nofollow" in headers
    assert "X-Frame-Options: DENY" in headers


def test_robots_disallows_all() -> None:
    robots = (BASE_DIR / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Disallow: /" in robots


# ---------------------------------------------------------------------------
# App screens share the studio shell (sidebar nav + AI status)
# ---------------------------------------------------------------------------
def test_app_pages_have_shell_navigation() -> None:
    for page in APP_PAGES:
        html = (BASE_DIR / page).read_text(encoding="utf-8")
        assert 'class="sidebar"' in html, f"sidebar missing in {page}"
        assert "AI 개인화 상태" in html or "검토 상태" in html, (
            f"AI status panel missing in {page}"
        )


def test_nav_pages_mark_active_section() -> None:
    for page in NAV_PAGES:
        html = (BASE_DIR / page).read_text(encoding="utf-8")
        assert 'aria-current="page"' in html, f"aria-current marker missing in {page}"


def test_onboarding_pages_do_not_falsely_mark_nav() -> None:
    for page in ONBOARDING_PAGES:
        html = (BASE_DIR / page).read_text(encoding="utf-8")
        assert 'aria-current="page"' not in html, (
            f"{page}: onboarding flow must not mark a main nav item as current"
        )


# ---------------------------------------------------------------------------
# Personalization is expressed as concrete change, not marketing fluff
# ---------------------------------------------------------------------------
def test_changes_screen_shows_concrete_comparison() -> None:
    html = (BASE_DIR / "changes/index.html").read_text(encoding="utf-8")
    for token in ("이전 수업", "다음 수업", "코드 먼저", "3개", "AI가 이렇게 바꾼 이유"):
        assert token in html, f"changes screen missing '{token}'"


def test_lesson2_is_visibly_code_first() -> None:
    html = (BASE_DIR / "lesson-2/index.html").read_text(encoding="utf-8")
    assert "코드 먼저" in html
    assert "예제 3개" in html
    # The code block (lesson_02.py) must appear before the explanation section
    # anchor, proving the lesson leads with code rather than prose.
    assert html.index("lesson_02.py") < html.index('id="l2-short"')


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
