"""Tests for the Cloudflare Pages static UI preview build.

Validates that the build produces all required pages, copies static assets,
and contains no Jinja tokens, secrets, localhost URLs, or external requests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.build_static_preview import main as build_main

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "dist-preview"

REQUIRED_PAGES = [
    "index.html",
    "admin/access/index.html",
    "admin/index.html",
    "admin/participants/modal-preview-user/index.html",
    "admin/review/modal-preview-edition/index.html",
    "preview/participant/access/index.html",
    "preview/participant/empty/index.html",
    "preview/participant/editing/index.html",
    "preview/participant/published/index.html",
    "preview/participant/feedback/index.html",
    "preview/participant/edition/index.html",
    "preview/participant/edition/feedback/index.html",
    "preview/participant/input/index.html",
    "preview/participant/history/index.html",
    "preview/participant/not-found/index.html",
]

JINJA_PATTERN = re.compile(r"\{\{|\{%")
LOCALHOST_PATTERN = re.compile(r"localhost|127\.0\.0\.1", re.IGNORECASE)
API_KEY_PATTERN = re.compile(r"sk-[a-zA-Z0-9]{20,}|AIza[a-zA-Z0-9_-]{35}")
CONN_STRING_PATTERN = re.compile(
    r"(postgresql|mongodb|mysql|redis|amqp)://", re.IGNORECASE
)
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
EXTERNAL_SCRIPT_PATTERN = re.compile(
    r'<script[^>]+src=["\']https?://', re.IGNORECASE
)
EXTERNAL_FETCH_PATTERN = re.compile(
    r"\bfetch\s*\(|XMLHttpRequest|\baxios\b", re.IGNORECASE
)
JWT_PATTERN = re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")
GH_TOKEN_PATTERN = re.compile(r"gh[pousr]_[a-zA-Z0-9]{36}")


@pytest.fixture(scope="module", autouse=True)
def _build_preview():
    build_main()


def _all_html_files() -> list[Path]:
    return sorted(OUTPUT_DIR.rglob("*.html"))


class TestRequiredPages:
    def test_all_required_pages_exist(self):
        for page in REQUIRED_PAGES:
            path = OUTPUT_DIR / page
            assert path.exists(), f"Missing page: {page}"

    def test_static_css_exists(self):
        assert (OUTPUT_DIR / "static" / "app.css").exists()

    def test_headers_file_exists(self):
        assert (OUTPUT_DIR / "_headers").exists()

    def test_robots_txt_exists(self):
        assert (OUTPUT_DIR / "robots.txt").exists()


class TestNoJinjaTokens:
    def test_no_jinja_expressions(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            matches = JINJA_PATTERN.findall(content)
            assert not matches, (
                f"Jinja tokens found in {html_file.relative_to(OUTPUT_DIR)}: {matches}"
            )


class TestNoLocalhost:
    def test_no_localhost_urls(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not LOCALHOST_PATTERN.search(content), (
                f"localhost/127.0.0.1 found in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestNoSecrets:
    def test_no_api_keys(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not API_KEY_PATTERN.search(content), (
                f"API key pattern found in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_connection_strings(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not CONN_STRING_PATTERN.search(content), (
                f"Connection string found in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_jwt_tokens(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not JWT_PATTERN.search(content), (
                f"JWT token found in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_github_tokens(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not GH_TOKEN_PATTERN.search(content), (
                f"GitHub token found in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_email_addresses(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not EMAIL_PATTERN.search(content), (
                f"Email address found in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestNoExternalRequests:
    def test_no_external_scripts(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not EXTERNAL_SCRIPT_PATTERN.search(content), (
                f"External script found in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_fetch_or_xhr(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert not EXTERNAL_FETCH_PATTERN.search(content), (
                f"External fetch/XHR found in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestPreviewBanner:
    def test_banner_present_on_all_pages(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert "UI Preview" in content, (
                f"Preview banner missing in {html_file.relative_to(OUTPUT_DIR)}"
            )
            assert "Synthetic data" in content, (
                f"Preview banner missing in {html_file.relative_to(OUTPUT_DIR)}"
            )
            assert "No persistence" in content, (
                f"Preview banner missing in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestRobotsMeta:
    def test_robots_meta_on_all_pages(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            assert 'name="robots"' in content, (
                f"robots meta missing in {html_file.relative_to(OUTPUT_DIR)}"
            )
            assert "noindex" in content, (
                f"noindex missing in {html_file.relative_to(OUTPUT_DIR)}"
            )
            assert "nofollow" in content, (
                f"nofollow missing in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestHeadersFile:
    def test_headers_content(self):
        headers = (OUTPUT_DIR / "_headers").read_text(encoding="utf-8")
        assert "X-Robots-Tag" in headers
        assert "noindex" in headers
        assert "Referrer-Policy" in headers
        assert "X-Content-Type-Options" in headers
        assert "X-Frame-Options" in headers
        assert "Content-Security-Policy" in headers


class TestLinkIntegrity:
    def _resolve_link(self, href: str) -> Path | None:
        href = href.strip()
        if not href or href.startswith(("http://", "https://", "mailto:", "#")):
            return None
        clean_href = href.split("?")[0].split("#")[0]
        if clean_href.startswith("/static/"):
            return OUTPUT_DIR / clean_href.lstrip("/")
        if clean_href == "/" or clean_href == "":
            return OUTPUT_DIR / "index.html"
        clean = clean_href.lstrip("/")
        if clean.endswith("/"):
            return OUTPUT_DIR / clean / "index.html"
        candidate_dir = OUTPUT_DIR / clean / "index.html"
        candidate_file = OUTPUT_DIR / f"{clean}.html"
        if candidate_dir.exists():
            return candidate_dir
        if candidate_file.exists():
            return candidate_file
        return OUTPUT_DIR / clean

    def test_internal_links_resolve(self):
        link_pattern = re.compile(r'href=["\']([^"\']+)["\']')
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            links = link_pattern.findall(content)
            for link in links:
                resolved = self._resolve_link(link)
                if resolved is None:
                    continue
                assert resolved.exists(), (
                    f"Broken link in {html_file.relative_to(OUTPUT_DIR)}: "
                    f"{link} -> {resolved.relative_to(OUTPUT_DIR)}"
                )


class TestBuildIdempotent:
    def test_rebuild_produces_same_files(self):
        first_run = sorted(p.relative_to(OUTPUT_DIR) for p in OUTPUT_DIR.rglob("*"))
        build_main()
        second_run = sorted(p.relative_to(OUTPUT_DIR) for p in OUTPUT_DIR.rglob("*"))
        assert first_run == second_run, "Rebuild produced different file set"
