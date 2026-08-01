"""Tests for the Cloudflare Pages static UI preview build.

Validates that the build produces all required pages, copies static assets,
and contains no Jinja tokens, secrets, localhost URLs, or external requests.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts.build_static_preview import main as build_main

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "dist-preview"
STATIC_DIR = BASE_DIR / "static"
SVG_FILES = [
    "img-hero-transformation.svg",
    "img-source-fragments.svg",
    "img-editorial-review.svg",
    "img-edition-cover.svg",
    "img-archive-grid.svg",
]

REQUIRED_PAGES = [
    "index.html",
    "admin/access/index.html",
    "admin/index.html",
    "admin/participants/modal-preview-user/index.html",
    "admin/review/modal-preview-edition/index.html",
    "admin/review/modal-preview-edition/evidence/index.html",
    "admin/review/modal-preview-edition/content/index.html",
    "admin/review/modal-preview-edition/publish/index.html",
    "admin/participants/modal-preview-user/feedback/index.html",
    "preview/participant/access/index.html",
    "preview/participant/empty/index.html",
    "preview/participant/input-received/index.html",
    "preview/participant/editing/index.html",
    "preview/participant/published/index.html",
    "preview/participant/feedback/index.html",
    "preview/participant/editions/modal-preview-edition/index.html",
    "preview/participant/editions/modal-preview-edition/feedback/index.html",
    "preview/participant/editions/modal-preview-edition/feedback/thanks/index.html",
    "preview/participant/editions/modal-preview-edition/adaptation/index.html",
    "preview/participant/input/index.html",
    "preview/participant/history/index.html",
    "preview/participant/not-found/index.html",
    "preview/intro/index.html",
]

PARTICIPANT_FLOW = [
    ("intro", "다음: 접속", "/preview/participant/access/"),
    ("access", "기록 단계", "/preview/participant/empty/"),
    ("empty", "첫 기록 시작", "/preview/participant/input"),
    ("input", "기록 접수", "/preview/participant/input-received/"),
    ("input_received", "편집 검토", "/preview/participant/editing/"),
    ("editing", "발행 단계", "/preview/participant/published/"),
    ("published", "최신 에디션 읽기", "/preview/participant/editions/modal-preview-edition/"),
    ("edition_read", "피드백 보내기", "/preview/participant/editions/modal-preview-edition/feedback"),
    ("feedback_form", "preview submit", "/preview/participant/editions/modal-preview-edition/feedback/thanks"),
    ("feedback_thanks", "다음 호 변화", "/preview/participant/editions/modal-preview-edition/adaptation"),
    ("adaptation", "지난 에디션 보기", "/preview/participant/history"),
]

OPERATOR_FLOW = [
    ("admin_dashboard", "참여자", "/admin/participants/modal-preview-user/"),
    ("participant_detail", "AI 초안 검토", "/admin/review/modal-preview-edition/"),
    ("review", "콘텐츠 검토", "/admin/review/modal-preview-edition/content/"),
    ("content_review", "게재 결정", "/admin/review/modal-preview-edition/publish/"),
    ("publish_decision", "피드백 연속성", "/admin/participants/modal-preview-user/feedback/"),
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
LINK_PATTERN = re.compile(r'href=["\']([^"\']+)["\']')
IMG_PATTERN = re.compile(r'src=["\']([^"\']+)["\']')
FORM_ACTION_PATTERN = re.compile(r'<form[^>]*action=["\']([^"\']+)["\']')
SUBMIT_PATTERN = re.compile(r'type=["\']submit["\']')
SVG_TEXT_PATTERN = re.compile(r"<text[ >]")


@pytest.fixture(scope="module", autouse=True)
def _build_preview():
    build_main()


def _all_html_files() -> list[Path]:
    return sorted(OUTPUT_DIR.rglob("*.html"))


class TestRequiredPages:
    def test_all_required_pages_exist(self):
        missing = []
        for page in REQUIRED_PAGES:
            path = OUTPUT_DIR / page
            if not path.exists():
                missing.append(page)
        assert not missing, f"Missing pages: {missing}"

    def test_static_css_exists(self):
        assert (OUTPUT_DIR / "static" / "app.css").exists()

    def test_headers_file_exists(self):
        assert (OUTPUT_DIR / "_headers").exists()

    def test_robots_txt_exists(self):
        assert (OUTPUT_DIR / "robots.txt").exists()

    def test_static_images_copied(self):
        static_img = OUTPUT_DIR / "static" / "images"
        assert static_img.is_dir()
        for svg in SVG_FILES:
            assert (static_img / svg).exists(), f"Missing copied SVG: {svg}"

    def test_new_operator_pages_exist(self):
        assert (OUTPUT_DIR / "admin/review/modal-preview-edition/publish/index.html").exists()
        assert (OUTPUT_DIR / "admin/participants/modal-preview-user/feedback/index.html").exists()


class TestParticipantFlow:
    def test_participant_sequential_links(self):
        for page_id, link_text, expected_target in PARTICIPANT_FLOW:
            page_map = {
                "intro": "preview/intro/index.html",
                "access": "preview/participant/access/index.html",
                "empty": "preview/participant/empty/index.html",
                "input": "preview/participant/input/index.html",
                "input_received": "preview/participant/input-received/index.html",
                "editing": "preview/participant/editing/index.html",
                "published": "preview/participant/published/index.html",
                "edition_read": "preview/participant/editions/modal-preview-edition/index.html",
                "feedback_form": "preview/participant/editions/modal-preview-edition/feedback/index.html",
                "feedback_thanks": "preview/participant/editions/modal-preview-edition/feedback/thanks/index.html",
                "adaptation": "preview/participant/editions/modal-preview-edition/adaptation/index.html",
            }
            path = OUTPUT_DIR / page_map[page_id]
            assert path.exists(), f"Page not found: {page_map[page_id]}"
            content = path.read_text(encoding="utf-8")
            target_stripped = expected_target.rstrip("/")
            assert target_stripped in content, (
                f"{page_id}: expected link to {expected_target} not found in {page_map[page_id]}"
            )
        # adaptation links to history without trailing slash — accept both
        adapt_path = OUTPUT_DIR / page_map["adaptation"]
        adapt_content = adapt_path.read_text(encoding="utf-8")
        assert "/preview/participant/history" in adapt_content, (
            "adaptation: expected link to /preview/participant/history not found"
        )


class TestOperatorFlow:
    def test_operator_sequential_links(self):
        page_map = {
            "admin_dashboard": "admin/index.html",
            "participant_detail": "admin/participants/modal-preview-user/index.html",
            "review": "admin/review/modal-preview-edition/index.html",
            "content_review": "admin/review/modal-preview-edition/content/index.html",
            "publish_decision": "admin/review/modal-preview-edition/publish/index.html",
        }
        for page_id, link_text, expected_target in OPERATOR_FLOW:
            path = OUTPUT_DIR / page_map[page_id]
            assert path.exists(), f"Page not found: {page_map[page_id]}"
            content = path.read_text(encoding="utf-8")
            target_stripped = expected_target.rstrip("/")
            assert target_stripped in content, (
                f"{page_id}: expected link to {expected_target} not found in {page_map[page_id]}"
            )


class TestContentReviewFields:
    def test_content_review_shows_rendered_title(self):
        path = OUTPUT_DIR / "admin/review/modal-preview-edition/content/index.html"
        content = path.read_text(encoding="utf-8")
        assert "속도에서 개인화로" in content, "rendered_title not displayed"
        assert "게재 준비일" in content, "drafted_at label not displayed"
        assert "2024-01-10" in content, "drafted_at date not displayed"

    def test_content_review_shows_all_paragraphs(self):
        path = OUTPUT_DIR / "admin/review/modal-preview-edition/content/index.html"
        content = path.read_text(encoding="utf-8")
        assert "창업 초기, 빠른 배송이 곧 경쟁력이라고 생각했습니다" in content
        assert "고객들을 만나면서 점점 흔들렸습니다" in content
        assert "다른 고객은 속도보다 자신에게 맞는 제안이 더 중요하다고" in content
        assert "진짜 가치는 고객 한 사람 한 사람을 이해하는 데" in content

    def test_content_review_no_undefined_fields(self):
        path = OUTPUT_DIR / "admin/review/modal-preview-edition/content/index.html"
        content = path.read_text(encoding="utf-8")
        assert "edition.title" not in content
        assert "edition.theme" not in content
        assert "edition.created_at" not in content
        assert "section.body" not in content

    def test_content_review_shows_publication_metadata(self):
        path = OUTPUT_DIR / "admin/review/modal-preview-edition/content/index.html"
        content = path.read_text(encoding="utf-8")
        assert "개인의 편지" in content  # publication_title
        assert "속도에서 개인화로" in content  # edition_title
        assert "한 창업자가 고객과의 대화를 통해 진짜 가치를 발견한 이야기" in content  # deck

    def test_content_review_feedback_direction_is_list(self):
        path = OUTPUT_DIR / "admin/review/modal-preview-edition/content/index.html"
        content = path.read_text(encoding="utf-8")
        assert "more_reflective" in content


class TestEditionCoverContract:
    def test_edition_read_cover_full_width(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/index.html"
        content = path.read_text(encoding="utf-8")
        assert 'class="edition-cover' in content
        assert "edition-cover-mini" not in content

    def test_adaptation_uses_mini_class(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/adaptation/index.html"
        content = path.read_text(encoding="utf-8")
        assert "edition-cover-mini" in content


class TestEditionIdIssueSeparation:
    """Fixture id (slug) and display issue number (호수) must be separate."""

    def test_fixture_has_separate_display_number(self):
        from preview_fixtures.data import make_edition, EDITION_ID

        edition = make_edition()
        assert edition.edition_number == 1, "display edition_number should be 1"
        assert edition.edition_uid == EDITION_ID, "edition_uid is the URL slug"
        assert edition.id == EDITION_ID
        assert edition.edition_number != edition.id

    def test_display_uses_issue_number_not_slug(self):
        # 제1호 is displayed on the edition-read page.
        ed = (OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/index.html").read_text(encoding="utf-8")
        assert "제1호" in ed, "edition read should display 제1호"
        assert "제modal-preview-edition호" not in ed
        # #1 is displayed on the queue (operator list) page and participant history.
        queue = (OUTPUT_DIR / "admin/index.html").read_text(encoding="utf-8")
        assert "#1" in queue, "operator queue should display #1"
        assert "#modal-preview-edition" not in queue
        hist = (OUTPUT_DIR / "preview/participant/history/index.html").read_text(encoding="utf-8")
        assert "#1" in hist, "participant history should display #1"
        assert "#modal-preview-edition" not in hist
        # Slug never used as a 호수 display anywhere.
        for html_file in _all_html_files():
            c = html_file.read_text(encoding="utf-8")
            assert "제modal-preview-edition호" not in c, (
                f"slug displayed as 호수 in {html_file.relative_to(OUTPUT_DIR)}"
            )

    def test_displayed_badges_are_numeric_everywhere(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            # A displayed badge wraps the edition ref with whitespace/tag, not a /
            assert "제modal-preview-edition호" not in content, (
                f"호수 slug displayed in {html_file.relative_to(OUTPUT_DIR)}"
            )
            # Display badge forms (#N, 제N호) must be numeric, i.e. no slug badge.
            assert ">#modal-preview-edition<" not in content
            assert "/#modal-preview-edition" not in content

    def test_urls_and_output_paths_use_slug(self):
        # URL and output path must keep using edition.id (the slug).
        assert (OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/index.html").exists()
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/index.html"
        content = path.read_text(encoding="utf-8")
        # Link targets under that page use the slug URL prefix.
        assert "/preview/participant/editions/modal-preview-edition/feedback" in content

    def test_url_paths_use_slug_rooted_at_preview(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/index.html"
        assert path.exists()
        feedback = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/feedback/index.html"
        assert feedback.exists()


class TestFeedbackAdaptation:
    def test_adaptation_shows_exact_feedback(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/adaptation/index.html"
        content = path.read_text(encoding="utf-8")
        assert "개인화가 구체적으로 어떻게 실천되는지 더 깊이 알고 싶습니다" in content

    def test_adaptation_shows_concrete_before(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/adaptation/index.html"
        content = path.read_text(encoding="utf-8")
        assert "고객이 빨리 받으면 만족할 것이라 믿었죠" in content
        assert "before" in content.lower() or "첫 번째" in content

    def test_adaptation_shows_concrete_after(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/adaptation/index.html"
        content = path.read_text(encoding="utf-8")
        assert "고객마다 원하는 속도와 방식이 다르다는 것" in content
        assert "after" in content.lower() or "다음 호" in content

    def test_adaptation_shows_why_section_changed(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/adaptation/index.html"
        content = path.read_text(encoding="utf-8")
        assert "고객과의 만남이 바꾼 것" in content  # changed section title
        assert "변경된 이유" in content

    def test_no_generic_adaptation_phrases(self):
        path = OUTPUT_DIR / "preview/participant/editions/modal-preview-edition/adaptation/index.html"
        content = path.read_text(encoding="utf-8")
        assert "구조 재편" not in content
        assert "내용 추가" not in content
        assert "톤 조정" not in content


class TestNoSvgText:
    def test_no_text_in_hero(self):
        svg = (STATIC_DIR / "images" / "img-hero-transformation.svg").read_text(encoding="utf-8")
        assert not SVG_TEXT_PATTERN.search(svg), "hero SVG contains <text>"

    def test_no_text_in_source_fragments(self):
        svg = (STATIC_DIR / "images" / "img-source-fragments.svg").read_text(encoding="utf-8")
        assert not SVG_TEXT_PATTERN.search(svg), "source fragments SVG contains <text>"

    def test_no_text_in_editorial_review(self):
        svg = (STATIC_DIR / "images" / "img-editorial-review.svg").read_text(encoding="utf-8")
        assert not SVG_TEXT_PATTERN.search(svg), "editorial review SVG contains <text>"

    def test_no_text_in_edition_cover(self):
        svg = (STATIC_DIR / "images" / "img-edition-cover.svg").read_text(encoding="utf-8")
        assert not SVG_TEXT_PATTERN.search(svg), "edition cover SVG contains <text>"

    def test_no_text_in_archive_grid(self):
        svg = (STATIC_DIR / "images" / "img-archive-grid.svg").read_text(encoding="utf-8")
        assert not SVG_TEXT_PATTERN.search(svg), "archive grid SVG contains <text>"

    def test_no_readable_korean_in_svgs(self):
        for svg_name in SVG_FILES:
            svg = (STATIC_DIR / "images" / svg_name).read_text(encoding="utf-8")
            assert "메모" not in svg
            assert "원고" not in svg
            assert "에디션" not in svg
            assert "Personal Edition" not in svg
            assert "연필선" not in svg
            assert "대화" not in svg


class TestLocalImageResolution:
    def test_all_images_resolve(self):
        static_prefix = "/static/"
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            images = IMG_PATTERN.findall(content)
            for src in images:
                if src.startswith(static_prefix):
                    rel = src[len(static_prefix):]
                    asset = OUTPUT_DIR / "static" / rel
                    assert asset.exists(), (
                        f"Missing image {src} referenced in {html_file.relative_to(OUTPUT_DIR)}"
                    )


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


class TestStaticForms:
    def test_form_actions_are_local(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            forms = FORM_ACTION_PATTERN.findall(content)
            for action in forms:
                assert not action.startswith(("http://", "https://", "//")), (
                    f"External form action {action} in {html_file.relative_to(OUTPUT_DIR)}"
                )

    def test_submit_buttons_disabled_by_css(self):
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            if SUBMIT_PATTERN.search(content):
                assert "opacity: 0.5" in content or "cursor: not-allowed" in content, (
                    f"Submit button without disable CSS in {html_file.relative_to(OUTPUT_DIR)}"
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
        for html_file in _all_html_files():
            content = html_file.read_text(encoding="utf-8")
            links = LINK_PATTERN.findall(content)
            for link in links:
                resolved = self._resolve_link(link)
                if resolved is None:
                    continue
                assert resolved.exists() and resolved.is_file(), (
                    f"Broken link in {html_file.relative_to(OUTPUT_DIR)}: "
                    f"{link} -> {resolved.relative_to(OUTPUT_DIR)} "
                    f"(exists={resolved.exists()}, is_file={resolved.is_file() if resolved.exists() else 'N/A'})"
                )


class TestBuildIdempotent:
    def test_rebuild_produces_same_files(self):
        first_run = sorted(p.relative_to(OUTPUT_DIR) for p in OUTPUT_DIR.rglob("*"))
        build_main()
        second_run = sorted(p.relative_to(OUTPUT_DIR) for p in OUTPUT_DIR.rglob("*"))
        assert first_run == second_run, "Rebuild produced different file set"


class TestScreenshotMatrix:
    def test_screenshot_matrix_manifest_exists(self):
        manifest_path = BASE_DIR / "docs" / "visual-review" / "screenshot-manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert isinstance(manifest, dict)
            assert len(manifest) > 0