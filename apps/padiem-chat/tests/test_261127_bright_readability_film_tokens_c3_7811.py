"""#7811 C3 — padiem-bright-readability.css 시네마틱 !important를 토큰으로.

시네마틱 상자 다섯(.sidebar, .topbar, .starter, .composer, .app-shell::before)에
붙어 있던 !important는 같은 대상을 다시 칠하는 규칙을 이기고 있었다. 이 정리는
그 상대 규칙이 padiem-tokens.css cinematic 블록의 토큰을 읽게 하고, 토큰 값은
예전 !important 리터럴 그대로 둔다. 선택자를 세게 만들어(body·.app-shell
앞붙이기) 이기는 방법은 쓰지 않는다. 그 방법이 다시 들어오면 여기서 잡힌다.

상대 규칙(실측, main):
* .sidebar 오른쪽 테두리 · .app-shell::before 불투명도·빛 — padiem-themes.css의
  같은 선택자 cinematic 규칙(뒤에 로드되어 이긴다).
* .topbar 배경·아래 테두리·그림자 — 넓은 폭에서 padiem-themes.css cinematic
  .topbar. 폰 폭에서는 interaction-polish.css의 !important가 원래 이겨서 여기
  값은 칠해진 적이 없다(죽은 선언).
* .composer 테두리·그림자 — home 상태 padiem-first-use.css, chat 상태
  padiem-rich.css.

.starter의 !important 3개는 남는다: 폰 폭 Claw 일반 화면에서
connector-pages.css가 카드를 지우는 규칙(투명·테두리 0·그림자 없음)을 이긴다.
토큰으로 옮기면 토큰 하나가 네 테마에서는 "카드 없음", 시네마틱에서는 "카드"를
뜻하게 되어 이번 정리에서 뺐다.
"""
from __future__ import annotations

import re

from _support import theme_sheets as sheets

BRIGHT = "padiem-bright-readability.css"
THEME_SHEET = "padiem-themes.css"
CIN = 'html[data-theme="cinematic"]'
BOXES = (".sidebar", ".topbar", ".starter", ".composer", ".app-shell::before")
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")

#: cinematic 블록의 새 토큰 → 값(예전 !important 리터럴 그대로).
FILM_TOKENS = {
    "--film-frame-edge": "rgba(136,201,255,.20)",
    "--film-rim-opacity": ".58",
    "--film-rim-blue-glow": "rgba(136,201,255,.18)",
    "--topbar-film-bg": "linear-gradient(180deg, rgba(7,11,19,.78), rgba(6,9,15,.16))",
    "--topbar-film-shadow": "inset 0 1px 0 rgba(255,255,255,.06), 0 10px 30px rgba(25,83,126,.12)",
    "--composer-film-edge": "rgba(136,201,255,.26)",
    "--composer-film-glow": (
        "0 0 40px rgba(93,178,246,.14), 0 18px 44px rgba(0,0,0,.28), "
        "inset 0 1px 0 rgba(255,255,255,.08)"),
}

#: 상대 규칙이 읽는 기존 토큰의 cinematic 값.
RIVAL_TOKEN_VALUES = {
    "--composer-home-edge": "var(--composer-film-edge)",
    "--composer-home-shadow": "var(--composer-film-glow)",
    "--rich-composer-border": "var(--composer-film-edge)",
    "--rich-composer-shadow": "var(--composer-film-glow)",
}

#: (시트, 선택자) → 토큰을 읽게 된 선언.
RIVALS = {
    (THEME_SHEET, f"{CIN} .app-shell::before"): {
        "opacity": "var(--film-rim-opacity)",
        "box-shadow": "0 0 16px var(--film-rim-blue-glow), 0 0 22px var(--film-gold-glow)",
    },
    (THEME_SHEET, f"{CIN} .sidebar"): {"border-right-color": "var(--film-frame-edge)"},
    (THEME_SHEET, f"{CIN} .topbar"): {
        "background": "var(--topbar-film-bg)",
        "border-bottom-color": "var(--film-frame-edge)",
        "box-shadow": "var(--topbar-film-shadow)",
    },
    ("padiem-first-use.css", '.app-shell[data-state="home"] .composer'): {
        "border-color": "var(--composer-home-edge)",
        "box-shadow": "var(--composer-home-shadow)",
    },
    ("padiem-rich.css", '.app-shell[data-state="chat"] .composer'): {
        "border-color": "var(--rich-composer-border)",
        "box-shadow": "var(--rich-composer-shadow)",
    },
}

#: 남는 !important(위 docstring의 .starter 사유).
KEPT_FLAGS = {
    (f"{CIN} .starter", "background"),
    (f"{CIN} .starter", "border-color"),
    (f"{CIN} .starter", "box-shadow"),
}


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _selectors(rule) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in rule.selector:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(_norm(current))
            current = ""
        else:
            current += char
    parts.append(_norm(current))
    return [part for part in parts if part]


def _declared(sheet_name: str, selector: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for rule in sheets.rules(sheet_name):
        if selector in _selectors(rule):
            for prop, value in sheets.decl_map(rule).items():
                found[prop] = _norm(value)
    return found


def _box_of(selector: str) -> str | None:
    for box in BOXES:
        if selector == box or selector.endswith(" " + box) or (
                box.startswith(".app-shell") and selector.endswith(box)):
            return box
    return None


def test_film_tokens_hold_the_former_flagged_literals_in_cinematic_only():
    for token, value in FILM_TOKENS.items():
        assert _norm(sheets.token_value("cinematic", token) or "") == value, token
        for theme in THEMES:
            if theme != "cinematic":
                assert sheets.token_value(theme, token) is None, (token, theme)


def test_the_rival_rules_read_the_film_tokens():
    for token, value in RIVAL_TOKEN_VALUES.items():
        assert sheets.token_value("cinematic", token) == value, token
    for (sheet_name, selector), expected in RIVALS.items():
        declared = _declared(sheet_name, selector)
        for prop, value in expected.items():
            assert declared.get(prop) == value, (sheet_name, selector, prop)


def test_the_readability_sheet_keeps_only_the_starter_and_composer_boxes():
    selectors = {s for rule in sheets.rules(BRIGHT) for s in _selectors(rule)}
    for box in (".sidebar", ".topbar", ".app-shell::before"):
        assert f"{CIN} {box}" not in selectors, box
    composer = _declared(BRIGHT, f"{CIN} .composer")
    assert composer["border-color"] == "var(--composer-film-edge)"
    assert composer["box-shadow"] == "var(--composer-film-glow)"


def test_only_the_starter_flags_remain_on_the_cinematic_boxes():
    flagged = set()
    for sheet_name in (BRIGHT, THEME_SHEET):
        for rule in sheets.rules(sheet_name):
            for selector in _selectors(rule):
                if selector.startswith(CIN) and _box_of(selector):
                    for prop, value in sheets.decl_map(rule).items():
                        if "!important" in value:
                            flagged.add((selector, prop))
    assert flagged == KEPT_FLAGS


def test_cinematic_box_selectors_are_not_strengthened():
    # 두 테마 시트의 시네마틱 상자 규칙은 `html[data-theme="cinematic"] <상자>`
    # 모양 그대로다. body·.app-shell 등을 앞에 붙여 특이도로 이기는 규칙이
    # 다시 들어오면 실패한다.
    for sheet_name in (BRIGHT, THEME_SHEET):
        for rule in sheets.rules(sheet_name):
            for selector in _selectors(rule):
                box = _box_of(selector)
                if selector.startswith(CIN) and box:
                    assert selector == f"{CIN} {box}", (sheet_name, selector)
    # 어떤 시트에도 시네마틱 상자를 body 밑으로 다시 고르는 선택자가 없다.
    body_prefix = re.compile(r'^html\[data-theme="cinematic"\]\s+body\s')
    for sheet_name in sheets.shipped_sheet_names():
        for rule in sheets.rules(sheet_name):
            for selector in _selectors(rule):
                if body_prefix.match(selector) and _box_of(selector):
                    raise AssertionError((sheet_name, selector))
