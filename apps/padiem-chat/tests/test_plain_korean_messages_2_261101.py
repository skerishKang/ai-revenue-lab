"""Regression checks for the second plain-language error pass."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
CHAT = ROOT / "apps" / "padiem-chat" / "static"
QUOTE = ROOT / "reference" / "business-66-padiem-quote-v1"


def test_visible_error_copy_has_no_embedded_technical_code():
    patterns = {
        CHAT / "calendar.js": [
            r"일정 조회에 실패했습니다 \(HTTP",
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
        text = path.read_text(encoding="utf-8")
        for pattern in expressions:
            assert not re.search(pattern, text), (path.name, pattern)


def test_reference_codes_are_separate_and_bounded():
    for path in (CHAT / "calendar.js", CHAT / "admin-models.js",
                 QUOTE / "quote-drive-ui.js",
                 QUOTE / "app.js"):
        text = path.read_text(encoding="utf-8")
        assert 'className = "error-code"' in text or '"error-code"' in text
        assert "참고 코드: " in text
        assert "[a-z0-9_]{0,63}" in text


def test_util_does_not_display_arbitrary_server_error_text():
    source = (CHAT / "util-menu.js").read_text(encoding="utf-8")
    api = source.split("async function apiChat(", 1)[1].split("async function getProjects(", 1)[0]
    assert "data?.error?.message" not in api
    assert 'error.code = typeof data?.error?.code === "string"' in api
    assert "GEN_ERROR_COPY[res.status]" in api


def test_util_generation_does_not_show_reference_codes():
    source = (CHAT / "util-menu.js").read_text(encoding="utf-8")
    failure = source.split("function showGenerationFailure(", 1)[1].split("function retryButton(", 1)[0]
    assert "참고 코드" not in failure
    assert "error.code" not in failure
    assert "generationFailureText(error)" in failure
