"""#8055 화면 픽셀 비교 범위 — 바뀐 시트가 닿는 화면만 고르는지.

도구(`tools/chat_pixel_compare.py`)는 playwright 를 import 하므로 이 시험은
의존성 없는 `tools/chat_pixel_scope.py`만 쓴다. 도구 쪽 화면 목록과 어긋나면
여기서 먼저 깨진다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.pixel_ttft_classification_source import read

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import chat_pixel_scope as scope  # noqa: E402

STATIC = ROOT / "apps/padiem-chat/static"
TOOL = ROOT / "tools" / "chat_pixel_compare.py"


def tool_screen_names() -> tuple[str, ...]:
    text = read(TOOL)
    block = re.search(r"^SCREENS = \((.*?)^\)$", text, re.S | re.M)
    assert block, "SCREENS 정의를 찾지 못했다"
    # 항목은 `    ("<이름>", "<페이지 파일>", ...` 로 시작한다(안쪽 튜플 제외).
    return tuple(re.findall(r'\n    \("([a-z0-9-]+)", "[a-z0-9.-]+"', block.group(1)))


def test_screen_names_match_the_pixel_tool() -> None:
    assert tool_screen_names() == scope.ALL_SCREENS


def test_every_sheet_on_disk_is_classified() -> None:
    mapping = scope.sheet_screen_map(STATIC)
    assert set(mapping) == {path.name for path in STATIC.glob("*.css")}
    for sheet, screens in mapping.items():
        assert screens, sheet
        assert set(screens) <= set(scope.ALL_SCREENS), sheet


def test_narrow_sheets_pick_only_their_screens() -> None:
    assert scope.screens_for_sheet(STATIC / "chat-feedback.css") == ("feedback-dialog",)
    util = scope.screens_for_sheet(STATIC / "util-menu.css")
    assert "util" in util
    assert not {"calendar", "library", "automation"} & set(util)
    claw = scope.screens_for_sheet(STATIC / "claw-workspace.css")
    assert "claw" in claw
    assert "util" not in claw
    library = scope.screens_for_sheet(STATIC / "library.css")
    assert "library" in library
    assert "util" not in library


def test_shared_and_unknown_sheets_stay_wide() -> None:
    # 공용 토큰 시트와 모르는 이름은 좁히지 않는다(넓게 비교).
    assert scope.screens_for_sheet(STATIC / "padiem-tokens.css") == scope.ALL_SCREENS
    assert scope.screens_for_sheets(STATIC, ["does-not-exist.css"]) == scope.ALL_SCREENS
    assert scope.screens_for_sheets(STATIC, []) == scope.ALL_SCREENS
    assert scope.screens_for_sheets(STATIC, ["util-menu.css", "nope.css"]) == scope.ALL_SCREENS


def test_selection_is_the_union_and_reduces_combos() -> None:
    selected = scope.screens_for_sheets(STATIC, ["util-menu.css", "chat-feedback.css"])
    assert selected == tuple(
        screen for screen in scope.ALL_SCREENS
        if screen in {"conversation", "util", "feedback-dialog"}
    )
    combos = 5 * 2 * len(selected)
    assert 1 < combos < 5 * 2 * len(scope.ALL_SCREENS)
    # 전 화면이 공용 시트에 걸리면 지금과 똑같이 140조합이다(느슨해지지 않음).
    assert len(scope.ALL_SCREENS) == 14


def test_tokens_reference_known_screens() -> None:
    assert set(scope.SCREEN_TOKENS) <= set(scope.ALL_SCREENS)
    # 홈 두 화면만 표식이 없다(앱 껍질 자체) — 나머지는 최소 하나씩 있어야
    # 시트 하나가 그 화면으로 좁혀질 수 있다.
    assert set(scope.ALL_SCREENS) - set(scope.SCREEN_TOKENS) == {"home-logout", "home-login"}
