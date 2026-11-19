#!/usr/bin/env python3
"""#8055 바뀐 CSS 시트 → 그 시트가 닿는 화면 목록.

PR 픽셀 비교는 테마 5 × 폭 2 × 화면 13 = 130조합이라 10~20분이 든다. 바뀐
시트의 선택자가 닿는 화면만 고르면 몇십 조합으로 줄어든다. 화면 이름은
`tools/chat_pixel_compare.py`의 `SCREENS`와 같아야 한다(시험이 대조한다).

판정은 느슨해지지 않는다(넓게 비교하는 쪽으로만 틀린다):
- 시트 본문에 화면 표식(`SCREEN_TOKENS`)이 하나도 없으면 그 시트는 전 화면에
  걸치는 공용 시트로 본다(ALL_SCREENS).
- 디스크에 없는 시트 이름·모르는 이름도 ALL_SCREENS.
- 여러 시트를 주면 각 시트가 닿는 화면의 합집합을 돌려준다.

시트 본문은 주석을 지운 뒤 소문자로 비교한다(선택자·값 어디에 있어도 표식이면
포함으로 본다 — 좁게 잡는 실수보다 넓게 잡는 쪽이 안전하다).
"""
from __future__ import annotations

import re
from pathlib import Path

# tools/chat_pixel_compare.py 의 SCREENS 와 같은 순서·이름.
ALL_SCREENS = (
    "home-logout",
    "home-login",
    "conversation",
    "claw",
    "util",
    "calendar",
    "automation",
    "library",
    "settings-dialog",
    "profile-menu",
    "feedback-dialog",
    "project-dialog",
    "auth-dialog",
)

# 화면을 알아보는 표식. index.html 한 장에 모든 화면이 들어 있어서(상태·창
# 열림으로 갈린다) "이 시트를 쓰는 화면"은 그 시트가 건드리는 영역으로 정한다.
SCREEN_TOKENS = {
    "conversation": ("#messagelist", ".message-", ".composer-", "#emptystate", ".conversation-"),
    "claw": ("[data-claw-card", ".claw-", "#padiem-claw"),
    "util": ("#util", ".util-"),
    "calendar": ("#calendarview", ".calendar-"),
    "automation": ("#automationview", ".automation-"),
    "library": ("#libraryview", ".library-"),
    "settings-dialog": ("#settingsdialog", ".padiem-settings", ".settings-"),
    "profile-menu": ("#profilemenu", ".profile-"),
    "feedback-dialog": ("#feedbackdialog", ".feedback-"),
    "project-dialog": ("#projectdialog", ".project-"),
    "auth-dialog": ("#authdialog", ".auth-"),
    # 홈 두 화면(로그아웃·로그인)은 앱 껍질 자체라 따로 좁히지 않는다 —
    # 표식이 없으면 공용 시트로 남아 전 화면과 함께 비교된다.
}

COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def sheet_text(path: Path) -> str:
    """시트 본문(주석 제거, 소문자)."""
    return COMMENT_RE.sub(" ", Path(path).read_text(encoding="utf-8")).lower()


def screens_for_sheet(path: Path) -> tuple[str, ...]:
    """시트 하나가 닿는 화면. 표식이 없으면 전 화면."""
    text = sheet_text(path)
    hits = tuple(
        screen for screen in ALL_SCREENS
        if any(token in text for token in SCREEN_TOKENS.get(screen, ()))
    )
    return hits or ALL_SCREENS


def sheet_screen_map(static_dir: Path) -> dict[str, tuple[str, ...]]:
    """정적 폴더의 모든 시트 → 화면 목록."""
    static = Path(static_dir)
    return {
        path.name: screens_for_sheet(path)
        for path in sorted(static.glob("*.css"))
    }


def screens_for_sheets(static_dir: Path, sheets: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """바뀐 시트 목록이 닿는 화면 합집합(ALL_SCREENS 순서).

    모르는 시트가 하나라도 있으면 전 화면을 돌려준다 — 좁히지 못한 것을
    "차이 없음"으로 통과시키지 않는다.
    """
    static = Path(static_dir)
    names = [name for name in (sheets or []) if name]
    if not names:
        return ALL_SCREENS
    selected: set[str] = set()
    for name in names:
        path = static / name
        if not path.is_file():
            return ALL_SCREENS
        selected.update(screens_for_sheet(path))
    return tuple(screen for screen in ALL_SCREENS if screen in selected)
