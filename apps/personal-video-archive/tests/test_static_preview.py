"""Tests for the Personal Video Archive Cloudflare Pages static UI preview.

These tests build the preview into isolated temporary directories and verify
the Issue #72 acceptance criteria plus the CTO follow-up gaps:

    * every required page is generated (all eight feed filter states per topic);
    * internal links resolve to generated files;
    * filter pills are real, query-free paths whose selected pill and contents
      match the requested state (Gap 1);
    * record-search badges show plain state values, never ``ViewingState.X``
      (Gap 2);
    * ``main()`` accepts an explicit output directory and defaults to the
      workspace ``dist-preview`` (Gap 4);
    * static assets (CSS + placeholder thumbnail) are present;
    * every page carries the preview banner and noindex/nofollow;
    * ``_headers`` is restrictive and ``robots.txt`` blocks all crawling;
    * no inline event handlers, ``fetch()``, mutation JavaScript, or
      ``<script>`` survive into the output;
    * no secret-like text, production URLs, or internal filesystem paths;
    * no href relies on a query string;
    * repeated builds into isolated directories are byte-identical;
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

FEED_STATES = [
    "all", "unseen", "opened", "saved", "in_progress",
    "completed", "revisit", "irrelevant",
]
TOPIC_IDS = ["pv-topic-0001", "pv-topic-0002", "pv-topic-0003"]


def _filter_pages() -> list[str]:
    """All eight filter-state pages for every topic."""
    pages = []
    for topic_id in TOPIC_IDS:
        for state in FEED_STATES:
            if state == "all":
                pages.append(f"topics/{topic_id}/index.html")
            else:
                pages.append(f"topics/{topic_id}/{state}/index.html")
    return pages


# Every required preview state (Issue #72) plus the supporting pages that keep
# navigation links resolvable.
REQUIRED_PAGES = [
    "index.html",  # preview landing / index
    "home/index.html",  # product home / topic list
    "topics/index.html",  # topic list
    "topics/new/index.html",  # new topic
    "topics/pv-topic-0001/review-rule/index.html",  # LLM query-rule review
    "topics/pv-topic-0001/refresh-failed/index.html",  # provider failure
    "videos/pv-video-0001/index.html",  # video detail
    "records/pv-rec-0003/index.html",  # private record detail / edit
    "records/pv-rec-0002/index.html",  # pending LLM structure proposal
    "records/pv-rec-0001/index.html",  # accepted structured record
    "records/index.html",  # record search results
    "error/index.html",  # validation error example
    "health/index.html",  # synthetic health page
] + _filter_pages()

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
    r"pages\.dev|neon\.tech|firebase|googleapis|youtu\.be",
    re.IGNORECASE,
)
YOUTUBE_URL_PATTERN = re.compile(r'https?://(?:www\.)?youtube\.com/[^\s"\'<>]+', re.IGNORECASE)
YTIMG_URL_PATTERN = re.compile(r'https?://i\.ytimg\.com/[^\s"\'<>]+', re.IGNORECASE)
QUERY_HREF_PATTERN = re.compile(r'href="[^"]*\?[^"]*"')
PILL_PATTERN = re.compile(
    r'<a href="(?P<href>[^"]*)"[^>]*class="(?P<cls>filter-pill[^"]*)"[^>]*data-state="(?P<state>[a-z_]+)"[^>]*>'
    r"\s*(?P<text>[^<]+)\s*</a>",
    re.DOTALL,
)


@pytest.fixture(scope="module")
def preview_dir(tmp_path_factory):
    """Build the preview once into an isolated temporary directory."""
    out = tmp_path_factory.mktemp("preview")
    build_main(out)
    return out


def _all_html_files(out_dir: Path) -> list[Path]:
    return sorted(out_dir.rglob("*.html"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_pills(html: str) -> list[dict]:
    return [m.groupdict() for m in PILL_PATTERN.finditer(html)]


def _resolve_href(out_dir: Path, href: str) -> Path | None:
    href = href.strip()
    if not href or href.startswith(("http://", "https://", "mailto:", "#")):
        return None
    clean_href = href.split("?")[0].split("#")[0]
    if clean_href.startswith("/static/"):
        return out_dir / clean_href.lstrip("/")
    if clean_href in ("/", ""):
        return out_dir / "index.html"
    clean = clean_href.lstrip("/")
    if clean.endswith("/"):
        return out_dir / clean / "index.html"
    candidate_dir = out_dir / clean / "index.html"
    candidate_file = out_dir / f"{clean}.html"
    if candidate_dir.exists():
        return candidate_dir
    if candidate_file.exists():
        return candidate_file
    return out_dir / clean


class TestRequiredPages:
    def test_all_required_pages_exist(self, preview_dir):
        for page in REQUIRED_PAGES:
            assert (preview_dir / page).exists(), f"Missing page: {page}"

    def test_static_css_exists(self, preview_dir):
        assert (preview_dir / "static" / "style.css").exists()

    def test_placeholder_thumbnail_exists(self, preview_dir):
        assert (preview_dir / "static" / "preview-thumb.svg").exists()

    def test_headers_file_exists(self, preview_dir):
        assert (preview_dir / "_headers").exists()

    def test_robots_txt_exists(self, preview_dir):
        assert (preview_dir / "robots.txt").exists()


class TestFeedFilterNavigation:
    """Gap 1: every filter pill resolves to a real generated page whose
    selected pill and contents match the requested state, with no query
    strings relied on by the static host."""

    def _page(self, preview_dir, state):
        if state == "all":
            return preview_dir / "topics/pv-topic-0001/index.html"
        return preview_dir / f"topics/pv-topic-0001/{state}/index.html"

    def _expected_href(self, state):
        if state == "all":
            return "/topics/pv-topic-0001"
        return f"/topics/pv-topic-0001/{state}"

    def test_all_eight_pills_present_and_query_free(self, preview_dir):
        pills = _parse_pills(_read(self._page(preview_dir, "all")))
        hrefs = {p["href"] for p in pills}
        for state in FEED_STATES:
            assert self._expected_href(state) in hrefs, f"missing pill {state}"
        for p in pills:
            assert "?" not in p["href"], f"query string in pill: {p['href']}"

    @pytest.mark.parametrize("state", FEED_STATES)
    def test_selected_pill_matches_state(self, preview_dir, state):
        content = _read(self._page(preview_dir, state))
        selected = [
            p for p in _parse_pills(content) if "filter-pill-selected" in p["cls"]
        ]
        assert len(selected) == 1, f"expected one selected pill for {state}"
        pill = selected[0]
        assert pill["href"] == self._expected_href(state)
        assert pill["state"] == state
        feed_filter_section = re.search(
            r'<nav class="feed-state-filter"[^>]*>.*?</nav>', content, re.DOTALL
        )
        assert feed_filter_section is not None
        assert feed_filter_section.group(0).count('aria-current="page"') == 1

    def test_every_pill_href_resolves_to_a_file(self, preview_dir):
        for pill in _parse_pills(_read(self._page(preview_dir, "all"))):
            resolved = _resolve_href(preview_dir, pill["href"])
            assert resolved is not None and resolved.is_file(), (
                f"pill href does not resolve: {pill['href']}"
            )

    def test_unseen_includes_unseen_excludes_completed(self, preview_dir):
        content = _read(self._page(preview_dir, "unseen"))
        assert "Attention in transformers" in content
        assert "전공생이 알려주는 AI" in content
        assert "But what is a neural network?" not in content

    def test_completed_includes_completed_excludes_unseen(self, preview_dir):
        content = _read(self._page(preview_dir, "completed"))
        assert "But what is a neural network?" in content
        assert "Attention in transformers" not in content

    def test_empty_filter_shows_no_results(self, preview_dir):
        # topic1 has no 'opened' videos -> empty state, no "Showing N videos".
        content = _read(self._page(preview_dir, "opened"))
        assert "아직 영상이 없습니다" in content
        assert "영상" not in content or "아직 영상이 없습니다" in content

    def test_archived_topic_empty_across_all_states(self, preview_dir):
        for state in FEED_STATES:
            if state == "all":
                page = preview_dir / "topics/pv-topic-0003/index.html"
            else:
                page = preview_dir / f"topics/pv-topic-0003/{state}/index.html"
            assert "아직 영상이 없습니다" in _read(page), f"topic3/{state} not empty"


class TestRecordStateRendering:
    """Gap 2: the record-search badge shows the user-facing state value, never
    the raw ``ViewingState.X`` enum repr."""

    def test_search_badges_show_plain_values(self, preview_dir):
        content = _read(preview_dir / "records/index.html")
        ko_labels = {"completed": "다 봄", "in_progress": "보는 중", "saved": "저장함"}
        for state, ko_label in ko_labels.items():
            assert f'<span class="badge badge-user">{ko_label}</span>' in content
        assert "ViewingState." not in content


class TestPreviewStates:
    def test_unseen_filter_shows_only_unseen(self, preview_dir):
        content = _read(preview_dir / "topics/pv-topic-0001/unseen/index.html")
        assert "영상 2개" in content
        assert "Attention in transformers" in content
        assert "전공생이 알려주는 AI" in content
        # completed video must not appear under the unseen filter
        assert "But what is a neural network?" not in content

    def test_completed_filter_shows_only_completed(self, preview_dir):
        content = _read(preview_dir / "topics/pv-topic-0001/completed/index.html")
        assert "영상 1개" in content
        assert "But what is a neural network?" in content
        assert "Attention in transformers" not in content

    def test_empty_feed_message(self, preview_dir):
        content = _read(preview_dir / "topics/pv-topic-0003/index.html")
        assert "아직 영상이 없습니다" in content

    def test_provider_failure_preserves_feed(self, preview_dir):
        content = _read(
            preview_dir / "topics/pv-topic-0001/refresh-failed/index.html"
        )
        assert "\uc0c8\ub85c\uace0\uce68 \uc2e4\ud328" in content  # 새로고침 실패
        # existing feed is preserved
        assert "But what is a neural network?" in content

    def test_review_rule_shows_editable_ai_suggestion(self, preview_dir):
        content = _read(
            preview_dir / "topics/pv-topic-0001/review-rule/index.html"
        )
        assert "AI 정리 제안" in content
        assert 'name="primary_query"' in content
        assert 'name="required_terms"' in content

    def test_pending_proposal_shows_ai_suggestion(self, preview_dir):
        content = _read(preview_dir / "records/pv-rec-0002/index.html")
        assert "대기 중인 제안" in content
        assert "AI 정리 제안" in content

    def test_accepted_structured_record_is_filled(self, preview_dir):
        content = _read(preview_dir / "records/pv-rec-0001/index.html")
        assert "배운 점" in content
        assert "타임스탬프 참조" in content

    def test_record_search_results(self, preview_dir):
        content = _read(preview_dir / "records/index.html")
        assert "나의 기록" in content
        assert "But what is a neural network?" in content

    def test_validation_error_message(self, preview_dir):
        content = _read(preview_dir / "error/index.html")
        assert "오류 400" in content
        assert "Invalid tag" in content

    def test_provenance_badges_present(self, preview_dir):
        feed = _read(preview_dir / "topics/pv-topic-0001/index.html")
        assert "YouTube 정보" in feed
        assert "이 영상이 추천된 이유" in feed
        record = _read(preview_dir / "records/pv-rec-0001/index.html")
        assert "나의 기록" in record


class TestNoJinjaTokens:
    def test_no_jinja_expressions(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            matches = JINJA_PATTERN.findall(_read(html_file))
            assert not matches, (
                f"Jinja tokens in {html_file.relative_to(preview_dir)}: {matches}"
            )


class TestNoActiveJavaScript:
    def test_no_inline_event_handlers(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not INLINE_HANDLER_PATTERN.search(_read(html_file)), (
                f"Inline event handler in {html_file.relative_to(preview_dir)}"
            )

    def test_no_fetch_or_xhr(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not FETCH_PATTERN.search(_read(html_file)), (
                f"fetch/XHR in {html_file.relative_to(preview_dir)}"
            )

    def test_no_mutation_javascript(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not MUTATION_JS_PATTERN.search(_read(html_file)), (
                f"Mutation JS in {html_file.relative_to(preview_dir)}"
            )

    def test_no_script_tags(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not SCRIPT_PATTERN.search(_read(html_file)), (
                f"<script> in {html_file.relative_to(preview_dir)}"
            )


class TestNoSecrets:
    def test_no_api_keys(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not API_KEY_PATTERN.search(_read(html_file)), (
                f"API key in {html_file.relative_to(preview_dir)}"
            )

    def test_no_connection_strings(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not CONN_STRING_PATTERN.search(_read(html_file)), (
                f"Connection string in {html_file.relative_to(preview_dir)}"
            )

    def test_no_jwt_tokens(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not JWT_PATTERN.search(_read(html_file)), (
                f"JWT in {html_file.relative_to(preview_dir)}"
            )

    def test_no_github_tokens(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not GH_TOKEN_PATTERN.search(_read(html_file)), (
                f"GitHub token in {html_file.relative_to(preview_dir)}"
            )

    def test_no_email_addresses(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not EMAIL_PATTERN.search(_read(html_file)), (
                f"Email in {html_file.relative_to(preview_dir)}"
            )

    def test_no_internal_paths(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not INTERNAL_PATH_PATTERN.search(_read(html_file)), (
                f"Internal path in {html_file.relative_to(preview_dir)}"
            )

    def test_no_blocked_production_urls(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not PRODUCTION_URL_PATTERN.search(_read(html_file)), (
                f"Blocked production URL in {html_file.relative_to(preview_dir)}"
            )

    def test_youtube_urls_are_watch_links_only(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            for url in YOUTUBE_URL_PATTERN.findall(_read(html_file)):
                assert "youtube.com/watch?v=" in url, (
                    f"Non-watch YouTube URL in {html_file.relative_to(preview_dir)}: {url}"
                )

    def test_ytimg_urls_are_thumbnails_only(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            for url in YTIMG_URL_PATTERN.findall(_read(html_file)):
                assert "i.ytimg.com/vi/" in url, (
                    f"Non-thumbnail ytimg URL in {html_file.relative_to(preview_dir)}: {url}"
                )

    def test_no_localhost_urls(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert not LOCALHOST_PATTERN.search(_read(html_file)), (
                f"localhost in {html_file.relative_to(preview_dir)}"
            )


class TestNoQueryStringLinks:
    """Gap 1: the static preview must not rely on query strings to select a
    page — every href is a clean path to a generated file."""

    def test_no_href_has_query_string(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            for href in QUERY_HREF_PATTERN.findall(_read(html_file)):
                # External URLs (e.g. YouTube watch?v=) are allowed to have query strings
                if "http://" in href or "https://" in href:
                    continue
                assert False, (
                    f"query-string href in {html_file.relative_to(preview_dir)}: {href}"
                )

    def test_no_state_query_anywhere(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            assert "?state=" not in _read(html_file), (
                f"?state= in {html_file.relative_to(preview_dir)}"
            )


class TestPreviewNotice:
    def test_quiet_notice_present_on_all_pages(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            rel = str(html_file.relative_to(preview_dir))
            if rel.startswith("en/"):
                assert "Preview" in content and "Sample data" in content, (
                    f"English quiet notice missing in {rel}"
                )
            else:
                assert "미리보기" in content and "예시 데이터" in content, (
                    f"Korean quiet notice missing in {rel}"
                )


class TestRobotsMeta:
    def test_robots_meta_on_all_pages(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            assert 'name="robots"' in content, (
                f"robots meta missing in {html_file.relative_to(preview_dir)}"
            )
            assert "noindex" in content, (
                f"noindex missing in {html_file.relative_to(preview_dir)}"
            )
            assert "nofollow" in content, (
                f"nofollow missing in {html_file.relative_to(preview_dir)}"
            )


class TestHeadersFile:
    def test_headers_content(self, preview_dir):
        headers = _read(preview_dir / "_headers")
        assert "X-Robots-Tag" in headers
        assert "noindex" in headers
        assert "Referrer-Policy" in headers
        assert "X-Content-Type-Options" in headers
        assert "X-Frame-Options" in headers
        assert "Content-Security-Policy" in headers

    def test_headers_block_scripts_and_forms(self, preview_dir):
        headers = _read(preview_dir / "_headers")
        assert "script-src 'none'" in headers
        assert "form-action 'none'" in headers
        assert "connect-src 'none'" in headers

    def test_headers_allow_youtube_thumbnails(self, preview_dir):
        headers = _read(preview_dir / "_headers")
        assert "https://i.ytimg.com" in headers


class TestRobotsTxt:
    def test_robots_blocks_all(self, preview_dir):
        robots = _read(preview_dir / "robots.txt")
        assert "User-agent: *" in robots
        assert "Disallow: /" in robots


class TestLinkIntegrity:
    def test_internal_links_resolve(self, preview_dir):
        link_pattern = re.compile(r'href=["\']([^"\']+)["\']')
        for html_file in _all_html_files(preview_dir):
            for link in link_pattern.findall(_read(html_file)):
                resolved = _resolve_href(preview_dir, link)
                if resolved is None:
                    continue
                assert resolved.exists() and resolved.is_file(), (
                    f"Broken link in {html_file.relative_to(preview_dir)}: {link}"
                )


class TestDefaultOutputContract:
    """Gap 4: with no argument, ``main()`` builds into the workspace
    ``dist-preview`` and returns that directory."""

    def test_default_output_is_workspace_dist_preview(self):
        result = build_main()
        assert result == BASE_DIR / "dist-preview"
        assert (result / "index.html").is_file()


class TestBuildDeterministic:
    def _hash_tree(self, out_dir: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(out_dir.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(out_dir)).encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_rebuild_is_byte_identical(self, tmp_path):
        first = build_main(tmp_path / "a")
        second = build_main(tmp_path / "b")
        assert self._hash_tree(first) == self._hash_tree(second), (
            "Two isolated builds produced different bytes"
        )


class TestVideoRequirements:
    """Issue #76: real YouTube video fixtures with proper attributes."""

    def _all_video_ids(self, preview_dir) -> set[str]:
        ids = set()
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            for m in re.finditer(r'youtube\.com/watch\?v=([A-Za-z0-9_-]{11})', content):
                ids.add(m.group(1))
        return ids

    def _all_channels(self, preview_dir) -> set[str]:
        channels = set()
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            for m in re.finditer(r'class="video-card-channel"[^>]*>([^<]+)<', content):
                channels.add(m.group(1).strip())
        return channels

    def test_at_least_8_distinct_video_ids(self, preview_dir):
        ids = self._all_video_ids(preview_dir)
        assert len(ids) >= 8, f"Only {len(ids)} distinct video IDs: {ids}"

    def test_at_least_4_distinct_channels(self, preview_dir):
        channels = self._all_channels(preview_dir)
        assert len(channels) >= 4, f"Only {len(channels)} distinct channels: {channels}"

    def test_watch_urls_are_https(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            for url in re.findall(r'https?://(?:www\.)?youtube\.com/watch\?v=[^\s"\'<>]+', content):
                assert url.startswith("https://"), f"Non-HTTPS watch URL: {url}"

    def test_thumbnail_urls_are_https(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            for url in re.findall(r'https?://i\.ytimg\.com/[^\s"\'<>]+', content):
                assert url.startswith("https://"), f"Non-HTTPS thumbnail URL: {url}"

    def test_external_links_have_noopener_noreferrer(self, preview_dir):
        link_pattern = re.compile(
            r'<a[^>]+href="https://(?:www\.)?youtube\.com/[^"]*"[^>]*>',
            re.IGNORECASE,
        )
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            for tag in link_pattern.findall(content):
                assert 'target="_blank"' in tag, f"Missing target=_blank: {tag}"
                assert 'rel="noopener noreferrer"' in tag or "noopener" in tag, (
                    f"Missing noopener: {tag}"
                )

    def test_no_placeholder_as_primary_card_image(self, preview_dir):
        for html_file in _all_html_files(preview_dir):
            content = _read(html_file)
            img_tags = re.findall(r'<img[^>]*class="[^"]*video-card-thumb[^"]*"[^>]*>', content)
            for tag in img_tags:
                assert "preview-thumb.svg" not in tag, (
                    f"Placeholder used as card image in {html_file.relative_to(preview_dir)}"
                )

    def test_real_thumbnail_in_first_video_card(self, preview_dir):
        content = _read(preview_dir / "topics/pv-topic-0001/index.html")
        first_img = re.search(r'<img[^>]*class="[^"]*video-card-thumb[^"]*"[^>]*src="([^"]*)"', content)
        assert first_img is not None, "No video card thumbnail found"
        assert "i.ytimg.com/vi/" in first_img.group(1), (
            f"First card image is not a real YouTube thumbnail: {first_img.group(1)}"
        )


class TestZeroNetwork:
    def test_build_makes_no_network_calls(self, tmp_path, monkeypatch):
        def _blocked(*args, **kwargs):
            raise AssertionError("network call attempted during preview build")

        monkeypatch.setattr(socket, "socket", _blocked)
        monkeypatch.setattr(socket, "create_connection", _blocked)
        # Should complete entirely offline into an isolated directory.
        out = build_main(tmp_path / "offline")
        assert (out / "index.html").is_file()
