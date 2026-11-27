"""Regression checks for the second plain-language error pass."""

# #8060: shipped reads live in _support; assertions stay here.
from _support.app_model_source import app_js, claw_status_js, council_app_js, feedback_css, feedback_js, frame_css, index_html, locale_js, read, usage_log_js
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
CHAT = ROOT / "apps" / "padiem-chat" / "static"
QUOTE = ROOT / "reference" / "business-66-padiem-quote-v1"


def test_visible_error_copy_has_no_embedded_technical_code():
    patterns = {
        CHAT / "calendar.js": [
            r"일정 보기에 실패했습니다 \(HTTP",
            r"캘린더 서버 오류가 발생했습니다 \(HTTP",
        ],
        CHAT / "admin-models.js": [
            r"관리 데이터를 불러오지 못했습니다\. \(",
        ],
        QUOTE / "quote-template-ui.js": [
            r"본뜨기를 진행할 수 없습니다 \(",
        ],
        QUOTE / "quote-drive-ui.js": [
            r"저장에 실패했습니다\. \(",
            r"이어서 저장하지 못했습니다\. \(",
            r"선택한 파일을 불러올 수 없습니다\. \(",
            r"\(import_helper_unavailable\)",
        ],
    }
    for path, expressions in patterns.items():
        text = read(path)
        for pattern in expressions:
            assert not re.search(pattern, text), (path.name, pattern)


def test_reference_codes_are_separate_and_bounded():
    for path in (CHAT / "calendar.js", CHAT / "admin-models.js",
                 QUOTE / "quote-drive-ui.js",
                 QUOTE / "app.js"):
        text = read(path)
        assert 'className = "error-code"' in text or '"error-code"' in text
        assert "참고 코드: " in text
        assert "[a-z0-9_]{0,63}" in text


def test_the_council_app_does_not_display_arbitrary_server_error_text():
    # 2026-11-01: generation moved to /apps/council/; the same rule holds there.
    source = council_app_js()
    api = source.split("async function apiChat(", 1)[1].split("// ── 저장 프로젝트", 1)[0]
    assert "data?.error?.message" not in api
    assert 'error.code = typeof data?.error?.code === "string"' in api
    assert "GEN_ERROR_COPY[res.status]" in api


def test_the_council_app_generation_does_not_show_reference_codes():
    source = council_app_js()
    failure = source.split("function generationFailureText(", 1)[1].split("function emptyResult(", 1)[0]
    assert "참고 코드" not in failure
    assert "error.code" not in failure
    assert "GEN_ERROR_COPY[error.status]" in failure
