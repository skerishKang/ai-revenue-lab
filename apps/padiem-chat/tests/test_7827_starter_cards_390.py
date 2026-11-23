"""#7827 — 390 폭 시작 카드: 설명 잘림 0, 칩 겹침 0, 1440 배치 불변.

390 폭에서 카드 설명(`.starter small`)이 한 줄 말줄임으로 잘렸다. 원인은
`chat-screen-polish.css`의 620 이하 규칙(`white-space: nowrap` +
`text-overflow: ellipsis`)이다. 같은 파일의 같은 규칙을 두 줄
clamp로 고친다. 칩(`.document-formats-toggle`) 자리는 손대지 않는다:
이미 확보된 위쪽 띠(`padding-top: 60px`)가 겹침을 막고 있다.

이 시험은 CSS 선언을 잠근다. 실제 겹침·잘림 숫자는 브라우저 QA
(`.github/scripts/b62_first_screen_cards_qa.py`, accessibility-browser-qa
단계 옆)가 잰다. 규칙: 새 `!important`·새 `[data-theme]` 덮어쓰기·새 polish
시트 금지.
"""


from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.ui_sheet_source_261103 import (
    chat_screen_polish_css, dark_contrast_css, first_use_css, history_css, index_html,
    mode_presentation_css, read, settings_css, sidebar_section_polish_css, six_panel_css,
    tokens_css, util_app_css, util_app_js, util_manifest_js, voice_composer_css,
)

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
POLISH = chat_screen_polish_css()
VOICE = voice_composer_css()
FIRST_USE = first_use_css()
SIDEBAR_POLISH = sidebar_section_polish_css()
THEME_SHEETS = {
    name: read(name)
    for name in (
        "padiem-themes.css",
        "padiem-glass.css",
        "padiem-dark-contrast.css",
        "padiem-bright-readability.css",
    )
}

NARROW_MEDIA = "@media (max-width: 620px)"
DESC_SELECTOR = (
    '.app-shell[data-layout-variant="conversation"]'
    " #emptyState:not([hidden]) .starter small"
)


def _media_block(sheet: str, media: str, must_contain: str) -> str:
    for start in range(len(sheet)):
        start = sheet.find(media, start)
        if start < 0:
            break
        depth = 0
        for i in range(sheet.index("{", start), len(sheet)):
            depth += (1 if sheet[i] == "{" else 0) - (1 if sheet[i] == "}" else 0)
            if depth == 0:
                block = sheet[start:i + 1]
                if must_contain in block:
                    return block
                break
    raise AssertionError(media)


def _rule_block(scope: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", scope)
    assert match, selector
    return match.group(1)


def _narrow_desc_block() -> str:
    return _rule_block(_media_block(POLISH, NARROW_MEDIA, DESC_SELECTOR), DESC_SELECTOR)


def test_narrow_description_clamps_two_lines_without_ellipsis() -> None:
    block = _narrow_desc_block()
    assert "-webkit-line-clamp: 2;" in block
    assert "line-clamp: 2;" in block
    # #7827: 잘림을 만들던 선언은 같은 규칙에서 나간다.
    assert "white-space" not in block
    assert "text-overflow" not in block
    # 규칙은 고치되 새로 고정하지 않는다.
    assert "!important" not in block
    assert "[data-theme" not in block


def test_chip_band_and_card_height_are_untouched() -> None:
    narrow = _media_block(POLISH, NARROW_MEDIA, DESC_SELECTOR)
    assert "padding-top: 60px !important;" in narrow
    shell_rule = _rule_block(VOICE, ".starter-grid .document-formats-toggle")
    assert "position: absolute;" in shell_rule
    assert "top: 10px;" in shell_rule
    assert "right: 11px;" in shell_rule
    home_rows = _rule_block(
        SIDEBAR_POLISH, ".app-shell[data-state=\"home\"] .starter-grid"
    )
    assert "grid-auto-rows: 145px;" in home_rows


def test_wide_layout_has_no_clamp_or_ellipsis_rule() -> None:
    outside = POLISH.replace(_media_block(POLISH, NARROW_MEDIA, DESC_SELECTOR), "")
    assert "line-clamp" not in outside
    assert ".starter small" not in outside
    # 1440은 4열 그대로다.
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in FIRST_USE


def test_no_theme_sheet_repaints_the_description() -> None:
    for name, sheet in THEME_SHEETS.items():
        for match in re.finditer(
            r"\.starter small\s*\{([^}]*)\}", sheet
        ):
            block = match.group(1)
            assert "white-space" not in block, name
            assert "text-overflow" not in block, name
            assert "line-clamp" not in block, name
