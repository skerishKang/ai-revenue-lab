"""Static validation tests for the Living Travel Cloudflare Pages preview.

These tests use **only** the Python standard library (no BeautifulSoup, no
requests, etc.) so they run without installing extra dependencies.

Run with:

    python -m pytest apps/living-travel/pages-preview/tests -q
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# tests/test_static_preview.py  →  pages-preview/  →  site/
SITE_DIR = Path(__file__).resolve().parents[1] / "site"

EXPECTED_PAGES = [
    "index.html",
    "traveler/enter.html",
    "traveler/dashboard.html",
    "traveler/edition.html",
    "traveler/history.html",
    "operator/login.html",
    "operator/dashboard.html",
    "operator/traveler-detail.html",
    "operator/edition-preview.html",
]

EXPECTED_ASSETS = [
    "assets/style.css",
    "robots.txt",
    "_headers",
]

# FastAPI POST paths that must NOT appear as form actions in the static preview.
FORBIDDEN_POST_ACTIONS = [
    "/operator/login",
    "/traveler/enter",
    "/traveler/preferences",
    "/traveler/deactivation-request",
    "/traveler/logout",
    "/traveler/editions/",
    "/operator/travelers/",
    "/operator/editions/",
    "/operator/logout",
]

# Patterns that indicate real personal information or secrets.
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\b\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4}\b")
# Common secret prefixes — must not appear in preview content.
SECRET_PREFIXES = ("sk-", "ghp_", "gho_", "AKIA", "xox", "LT_OPERATOR_SECRET")

SYNTHETIC_MARKER = "Synthetic Preview"


# ---------------------------------------------------------------------------
# HTML parser helper
# ---------------------------------------------------------------------------


class _LinkExtractor(HTMLParser):
    """Collect href, src, and form action/method attributes from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.srcs: list[str] = []
        self.form_actions: list[tuple[str, str]] = []  # (action, method)
        self.text_parts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "a":
            href = attr_map.get("href")
            if href:
                self.hrefs.append(href)
        if tag in ("link", "img", "script", "iframe"):
            src = attr_map.get("src") or attr_map.get("href")
            if src:
                self.srcs.append(src)
        if tag == "form":
            action = attr_map.get("action", "")
            method = attr_map.get("method", "get").lower()
            self.form_actions.append((action, method))
        if tag == "script":
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if not self._in_script:
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts)


def _read_html(rel_path: str) -> str:
    return (SITE_DIR / rel_path).read_text(encoding="utf-8")


def _parse(rel_path: str) -> _LinkExtractor:
    parser = _LinkExtractor()
    parser.feed(_read_html(rel_path))
    return parser


def _resolve(base_rel: str, link: str) -> str:
    """Resolve *link* relative to *base_rel* and return a normalised path."""
    # urljoin handles relative resolution correctly for file-style paths.
    resolved = urljoin(base_rel, link)
    # Strip any query/fragment.
    resolved = resolved.split("#")[0].split("?")[0]
    return resolved


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFileStructure(unittest.TestCase):
    """Verify that every expected file exists in the site directory."""

    def test_site_dir_exists(self) -> None:
        self.assertTrue(SITE_DIR.is_dir(), f"Site directory not found: {SITE_DIR}")

    def test_all_expected_pages_exist(self) -> None:
        for page in EXPECTED_PAGES:
            path = SITE_DIR / page
            self.assertTrue(path.exists(), f"Missing page: {page}")

    def test_all_expected_assets_exist(self) -> None:
        for asset in EXPECTED_ASSETS:
            path = SITE_DIR / asset
            self.assertTrue(path.exists(), f"Missing asset: {asset}")

    def test_css_is_non_empty(self) -> None:
        css = (SITE_DIR / "assets/style.css").read_text(encoding="utf-8")
        self.assertGreater(len(css), 100, "style.css is suspiciously small")


class TestInternalLinks(unittest.TestCase):
    """Every internal link must resolve to an existing file."""

    def test_all_links_resolve(self) -> None:
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            parser = _parse(page)
            for href in parser.hrefs:
                if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                if href.startswith(("http://", "https://")):
                    errors.append(f"{page}: external link {href}")
                    continue
                resolved = _resolve(page, href)
                target = SITE_DIR / resolved
                if not target.exists():
                    errors.append(f"{page}: link '{href}' → '{resolved}' does not exist")
        self.assertEqual(errors, [], "Broken internal links:\n" + "\n".join(errors))

    def test_all_assets_resolve(self) -> None:
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            parser = _parse(page)
            for src in parser.srcs:
                if not src or src.startswith(("http://", "https://")):
                    continue
                resolved = _resolve(page, src)
                target = SITE_DIR / resolved
                if not target.exists():
                    errors.append(f"{page}: asset '{src}' → '{resolved}' does not exist")
        self.assertEqual(errors, [], "Broken asset references:\n" + "\n".join(errors))


class TestNoExternalRequests(unittest.TestCase):
    """No external network requests (CDN, fonts, images, scripts)."""

    def test_no_external_urls(self) -> None:
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            parser = _parse(page)
            for href in parser.hrefs + parser.srcs:
                if href and (
                    href.startswith("http://") or href.startswith("https://")
                ):
                    errors.append(f"{page}: external URL {href}")
        self.assertEqual(errors, [], "External URLs found:\n" + "\n".join(errors))


class TestNoFastApiPostPaths(unittest.TestCase):
    """Forms must not POST to FastAPI backend paths."""

    def test_no_forbidden_form_actions(self) -> None:
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            parser = _parse(page)
            for action, method in parser.form_actions:
                if method == "post":
                    for forbidden in FORBIDDEN_POST_ACTIONS:
                        if forbidden in action:
                            errors.append(
                                f"{page}: POST form action '{action}' matches forbidden '{forbidden}'"
                            )
        self.assertEqual(
            errors, [], "Forbidden POST actions found:\n" + "\n".join(errors)
        )

    def test_forms_do_not_submit_to_backend(self) -> None:
        """Every <form> must either use action='#' or onsubmit='return false'."""
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            html = _read_html(page)
            # Find all <form ...> tags
            for match in re.finditer(r"<form\b([^>]*)>", html, re.IGNORECASE):
                tag = match.group(1)
                if "action=" in tag.lower() and "action=\"#" not in tag.lower() and "action='#'" not in tag.lower():
                    # Check if it's a real backend path
                    action_match = re.search(r'action=["\']([^"\']*)["\']', tag, re.IGNORECASE)
                    if action_match:
                        action = action_match.group(1)
                        if action.startswith("/") and not action.startswith("/#"):
                            errors.append(f"{page}: form posts to backend path '{action}'")
        self.assertEqual(
            errors, [], "Forms posting to backend paths:\n" + "\n".join(errors)
        )


class TestSyntheticNotice(unittest.TestCase):
    """Every page must display the synthetic preview notice."""

    def test_synthetic_marker_present(self) -> None:
        for page in EXPECTED_PAGES:
            text = _parse(page).text
            self.assertIn(
                SYNTHETIC_MARKER,
                text,
                f"{page}: missing '{SYNTHETIC_MARKER}' notice",
            )


class TestNoPersonalInfo(unittest.TestCase):
    """No real personal information or secrets in preview content."""

    def test_no_email_addresses(self) -> None:
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            text = _parse(page).text
            for match in EMAIL_RE.finditer(text):
                errors.append(f"{page}: email address found: {match.group()}")
        self.assertEqual(errors, [], "Email addresses found:\n" + "\n".join(errors))

    def test_no_phone_numbers(self) -> None:
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            text = _parse(page).text
            for match in PHONE_RE.finditer(text):
                errors.append(f"{page}: phone number found: {match.group()}")
        self.assertEqual(errors, [], "Phone numbers found:\n" + "\n".join(errors))

    def test_no_secret_prefixes(self) -> None:
        errors: list[str] = []
        for page in EXPECTED_PAGES:
            text = _parse(page).text
            for prefix in SECRET_PREFIXES:
                if prefix in text:
                    errors.append(f"{page}: secret prefix '{prefix}' found")
        self.assertEqual(errors, [], "Secret prefixes found:\n" + "\n".join(errors))


class TestRobotsTxt(unittest.TestCase):
    """robots.txt must block all crawlers."""

    def test_robots_blocks_all(self) -> None:
        content = (SITE_DIR / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *", content)
        self.assertIn("Disallow: /", content)


class TestHeaders(unittest.TestCase):
    """_headers must include required security directives."""

    def test_headers_content(self) -> None:
        content = (SITE_DIR / "_headers").read_text(encoding="utf-8")
        self.assertIn("noindex", content)
        self.assertIn("nofollow", content)
        self.assertIn("Referrer-Policy", content)
        self.assertIn("nosniff", content)
        self.assertIn("X-Frame-Options", content)
        self.assertIn("Content-Security-Policy", content)


class TestCssContent(unittest.TestCase):
    """CSS must include key accessibility and responsive features."""

    def test_has_focus_styles(self) -> None:
        css = (SITE_DIR / "assets/style.css").read_text(encoding="utf-8")
        self.assertIn("focus", css.lower(), "CSS missing focus styles")

    def test_has_responsive_media_query(self) -> None:
        css = (SITE_DIR / "assets/style.css").read_text(encoding="utf-8")
        self.assertIn("@media", css, "CSS missing responsive media query")

    def test_no_external_fonts(self) -> None:
        css = (SITE_DIR / "assets/style.css").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis.com", css)
        self.assertNotIn("fonts.gstatic.com", css)


if __name__ == "__main__":
    unittest.main()
