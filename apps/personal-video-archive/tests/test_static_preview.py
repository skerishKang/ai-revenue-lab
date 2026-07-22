"""Tests for the Personal Video Archive Cloudflare Pages static UI preview.

These tests build the preview from a clean output directory and verify the
Issue #72 acceptance criteria:

    * every required page is generated;
    * internal links resolve to generated files;
    * static assets (CSS + placeholder thumbnail) are present;
    * every page carries the preview banner and noindex/nofollow;
    * ``_headers`` is restrictive and ``robots.txt`` blocks all crawling;
    * no inline event handlers, ``fetch()``, mutation JavaScript, or
      ``<script>`` survive into the output;
    * no secret-like text, production URLs, or internal filesystem paths;
    * repeated builds are byte-identical (deterministic);
    * the build performs zero network calls.

No database, FastAPI server, provider, API key, or network access is used.
"""

from __future__ import annotations

import hashlib
import re
import socket
from pathlib import Path

import pytest

from scripts.build_static_preview import main as build_main

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "dist-preview"

# Every required preview state (Issue #72) plus the supporting pages that keep
# navigation links resolvable.
REQUIRED_PAGES = [
    "index.html",  # preview landing / index
    "home/index.html",  # product home / topic list
    "topics/index.html",  # topic list
    "topics/new/index.html",  # new topic
    "topics/pv-topic-0001/review-rule/index.html",  # LLM query-rule review
    "topics/pv-topic-0001/index.html",  # populated newest-first feed
    "topics/pv-topic-0001/unseen/index.html",  # unseen filter
    "topics/pv-topic-0001/completed/index.html",  # completed filter
    "topics/pv-topic-0001/empty/index.html",  # empty / no-results feed
    "topics/pv-topic-0001/refresh-failed/index.html",  # provider failure
    "topics/pv-topic-0002/index.html",  # secondary topic feed
    "topics/pv-topic-0003/index.html",  # archived topic feed
    "videos/pv-video-0001/index.html",  # video detail
    "records/pv-rec-0003/index.html",  # private record detail / edit
    "records/pv-rec-0002/index.html",  # pending LLM structure proposal
    "records/pv-rec-0001/index.html",  # accepted structured record
    "records/index.html",  # record search results
    "error/index.html",  # validation error example
    "health/index.html",  # synthetic health page
]

JINJA_PATTERN = re.compile(r"\{\{|\{%")
LOCALHOST_PATTERN = re.compile(r"localhost|127\.0\.0\.1", re.IGNORECASE)
API_KEY_PATTERN = re.compile(r"sk-[a-zA-Z0-9]{20,}|AIza[a-zA-Z0-9_-]{35}")
CONN_STRING_PATTERN = re.compile(
    r"(postgresql|mongodb|mysql|redis|amqp)://", re.IGNORECASE
)
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
JWT_PATTERN = re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")
GH_TOKEN_PATTERN = re.compile(r"gh[pousr]_[a-zA-Z0-9]{36}")
INLINE_HANDLER_PATTERN = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
FETCH_PATTERN = re.compile(r"\bfetch\s*\(|XMLHttpRequest|\baxios\b", re.IGNORECASE)
MUTATION_JS_PATTERN = re.compile(r"\.submit\s*\(|window\.open\s*\(", re.IGNORECASE)
SCRIPT_PATTERN = re.compile(r"<script", re.IGNORECASE)
INTERNAL_PATH_PATTERN = re.compile(
    r"/mnt/|G:\\|C:\\|/Users/|/home/[a-z]", re.IGNORECASE
)
PRODUCTION_URL_PATTERN = re.compile(
    r"youtube\.com|youtu\.be|pages\.dev|neon\.tech|firebase|googleapis",
    re.IGNORECASE,
)


@pytest.fixture(scope="module", autouse=True)
def _build_preview():
    build_main()


def _all_html_files() -> list[Path]:
    return sorted(OUTPUT_DIR.rglob("*.html"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestRequiredPages:
    def test_all_required_pages_exist(self):
        for page in REQUIRED_PAGES:
            assert (OUTPUT_DIR / page).exists(), f"Missing page: {page}"

    def test_static_css_exists(self):
        assert (OUTPUT_DIR / "static" / "style.css").exists()

    def test_placeholder_thumbnail_exists(self):
        assert (OUTPUT_DIR / "static" / "preview-thumb.svg").exists()

    def test_headers_file_exists(self):
        assert (OUTPUT_DIR / "_headers").exists()

    def test_robots_txt_exists(self):
        assert (OUTPUT_DIR / "robots.txt").exists()


class TestPreviewStates:
    def test_unseen_filter_shows_only_unseen(self):
        content = _read(OUTPUT_DIR / "topics/pv-topic-0001/unseen/index.html")
        assert "Showing 2 videos" in content
        assert "Synthetic PyTorch Lightning Crash Course" in content
        assert "Synthetic Lecture: Optimization Internals" in content
        # completed video must not appear under the unseen filter
        assert "Tensors and Autograd" not in content

    def test_completed_filter_shows_only_completed(self):
        content = _read(OUTPUT_DIR / "topics/pv-topic-0001/completed/index.html")
        assert "Showing 1 videos" in content
        assert "Tensors and Autograd" in content
        assert "Synthetic PyTorch Lightning Crash Course" not in content

    def test_empty_feed_message(self):
        content = _read(OUTPUT_DIR / "topics/pv-topic-0001/empty/index.html")
        assert "No videos yet" in content

    def test_provider_failure_preserves_feed(self):
        content = _read(
            OUTPUT_DIR / "topics/pv-topic-0001/refresh-failed/index.html"
        )
        assert "\uc0c8\ub85c\uace0\uce68 \uc2e4\ud328" in content  # 새로고침 실패
        # existing feed is preserved
        assert "Tensors and Autograd" in content

    def test_review_rule_shows_editable_ai_suggestion(self):
        content = _read(
            OUTPUT_DIR / "topics/pv-topic-0001/review-rule/index.html"
        )
        assert "AI Suggestion" in content
        assert 'name="primary_query"' in content
        assert 'name="required_terms"' in content

    def test_pending_proposal_shows_ai_suggestion(self):
        content = _read(OUTPUT_DIR / "records/pv-rec-0002/index.html")
        assert "Pending Proposals" in content
        assert "AI Suggestion" in content

    def test_accepted_structured_record_is_filled(self):
        content = _read(OUTPUT_DIR / "records/pv-rec-0001/index.html")
        assert "What I Learned" in content
        assert "Timestamp References" in content

    def test_record_search_results(self):
        content = _read(OUTPUT_DIR / "records/index.html")
        assert "My Records" in content
        assert "Tensors and Autograd" in content

    def test_validation_error_message(self):
        content = _read(OUTPUT_DIR / "error/index.html")
        assert "Error 400" in content
        assert "Invalid tag" in content

    def test_provenance_badges_present(self):
        feed = _read(OUTPUT_DIR / "topics/pv-topic-0001/index.html")
        assert "YouTube info" in feed
        assert "Application analysis" in feed
        record = _read(OUTPUT_DIR / "records/pv-rec-0001/index.html")
        assert "My private record" in record


class TestNoJinjaTokens:
    def test_no_jinja_expressions(self):
        for html_file in _all_html_files():
            matches = JINJA_PATTERN.findall(_read(html_file))
            assert not matches, (
                f"Jinja tokens in {html_file.relative_to(OUTPUT_DIR)}: {matches}"
            )


class TestNoActiveJavaScript:
    def test_no_inline_event_handlers(self):
        for html_file in _all_html_files():
            assert not INLINE_HANDLER_PATTERN.search(_read(html_file)), (
                f"Inline event handler in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_fetch_or_xhr(self):
        for html_file in _all_html_files():
            assert not FETCH_PATTERN.search(_read(html_file)), (
                f"fetch/XHR in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_mutation_javascript(self):
        for html_file in _all_html_files():
            assert not MUTATION_JS_PATTERN.search(_read(html_file)), (
                f"Mutation JS in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_script_tags(self):
        for html_file in _all_html_files():
            assert not SCRIPT_PATTERN.search(_read(html_file)), (
                f"<script> in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestNoSecrets:
    def test_no_api_keys(self):
        for html_file in _all_html_files():
            assert not API_KEY_PATTERN.search(_read(html_file)), (
                f"API key in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_connection_strings(self):
        for html_file in _all_html_files():
            assert not CONN_STRING_PATTERN.search(_read(html_file)), (
                f"Connection string in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_jwt_tokens(self):
        for html_file in _all_html_files():
            assert not JWT_PATTERN.search(_read(html_file)), (
                f"JWT in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_github_tokens(self):
        for html_file in _all_html_files():
            assert not GH_TOKEN_PATTERN.search(_read(html_file)), (
                f"GitHub token in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_email_addresses(self):
        for html_file in _all_html_files():
            assert not EMAIL_PATTERN.search(_read(html_file)), (
                f"Email in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_internal_paths(self):
        for html_file in _all_html_files():
            assert not INTERNAL_PATH_PATTERN.search(_read(html_file)), (
                f"Internal path in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_production_urls(self):
        for html_file in _all_html_files():
            assert not PRODUCTION_URL_PATTERN.search(_read(html_file)), (
                f"Production URL in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_no_localhost_urls(self):
        for html_file in _all_html_files():
            assert not LOCALHOST_PATTERN.search(_read(html_file)), (
                f"localhost in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestPreviewBanner:
    def test_banner_present_on_all_pages(self):
        for html_file in _all_html_files():
            content = _read(html_file)
            assert "UI Preview" in content, (
                f"Banner missing in {html_file.relative_to(OUTPUT_DIR)}"
            )
            assert "Synthetic data" in content, (
                f"Banner missing in {html_file.relative_to(OUTPUT_DIR)}"
            )
            assert "No persistence" in content, (
                f"Banner missing in {html_file.relative_to(OUTPUT_DIR)}"
            )


class TestRobotsMeta:
    def test_robots_meta_on_all_pages(self):
        for html_file in _all_html_files():
            content = _read(html_file)
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
        headers = _read(OUTPUT_DIR / "_headers")
        assert "X-Robots-Tag" in headers
        assert "noindex" in headers
        assert "Referrer-Policy" in headers
        assert "X-Content-Type-Options" in headers
        assert "X-Frame-Options" in headers
        assert "Content-Security-Policy" in headers

    def test_headers_block_scripts_and_forms(self):
        headers = _read(OUTPUT_DIR / "_headers")
        assert "script-src 'none'" in headers
        assert "form-action 'none'" in headers
        assert "connect-src 'none'" in headers


class TestRobotsTxt:
    def test_robots_blocks_all(self):
        robots = _read(OUTPUT_DIR / "robots.txt")
        assert "User-agent: *" in robots
        assert "Disallow: /" in robots


class TestLinkIntegrity:
    def _resolve_link(self, href: str) -> Path | None:
        href = href.strip()
        if not href or href.startswith(("http://", "https://", "mailto:", "#")):
            return None
        clean_href = href.split("?")[0].split("#")[0]
        if clean_href.startswith("/static/"):
            return OUTPUT_DIR / clean_href.lstrip("/")
        if clean_href in ("/", ""):
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
            for link in link_pattern.findall(_read(html_file)):
                resolved = self._resolve_link(link)
                if resolved is None:
                    continue
                assert resolved.exists() and resolved.is_file(), (
                    f"Broken link in {html_file.relative_to(OUTPUT_DIR)}: {link}"
                )


class TestBuildDeterministic:
    def _hash_tree(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(OUTPUT_DIR.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(OUTPUT_DIR)).encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_rebuild_is_byte_identical(self):
        first = self._hash_tree()
        build_main()
        second = self._hash_tree()
        assert first == second, "Rebuild produced different bytes"


class TestZeroNetwork:
    def test_build_makes_no_network_calls(self, monkeypatch):
        def _blocked(*args, **kwargs):
            raise AssertionError("network call attempted during preview build")

        monkeypatch.setattr(socket, "socket", _blocked)
        monkeypatch.setattr(socket, "create_connection", _blocked)
        # Should complete entirely offline.
        build_main()
        assert (OUTPUT_DIR / "index.html").exists()
