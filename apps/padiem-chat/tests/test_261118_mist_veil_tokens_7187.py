"""#7187 7차 — 옅은 안개(면·글자·선·하이라이트) 토큰.

남은 색 리터럴 전수표에서 값 ``rgba(255, 255, 255, .34)`` 묶음(12선언·5시트)을
쓰임새별 네 토큰으로 옮긴다.

* ``--surface-veil-mist`` — 배경 6선언(#8001에서 glass 닫기 단추 1선언이
  --card-bg 한 판 토큰으로 바뀌며 계약에서 빠졌다).
* ``--text-veil-mist`` — 글자 2선언(별도 계약: test_261118_white_veil_text_tokens_7187).
* ``--line-veil-mist`` — 테두리 3선언.
* ``--inset-veil-mist`` — ``0 0 0 1px`` 하이라이트 1선언.

값은 치환 전 리터럴 그대로고 테마 블록에서는 덮지 않는다. 6차 댓글에 적은
덮어쓰기 후보 7선언은 이번에도 값만 옮기고 화면은 그대로다. 사이드바 시트와
``padiem-glass.css``는 건드리지 않는다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from css_rules import parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

ROOT_TOKENS = {
    "--surface-veil-mist": "rgba(255, 255, 255, .34)",
    "--text-veil-mist": "rgba(255, 255, 255, .34)",
    "--line-veil-mist": "rgba(255, 255, 255, .34)",
    "--inset-veil-mist": "rgba(255, 255, 255, .34)",
}

CHANGED = {
    "claw-focus-layout.css": {
        ("background", "var(--surface-veil-mist)"): 6,
    },
    "padiem-cinematic-workspace.css": {
        ("color", "var(--text-veil-mist) !important"): 1,
        ("color", "var(--text-veil-mist)"): 1,
        ("border-color", "var(--line-veil-mist) !important"): 1,
    },
    "padiem-glass-brand-polish.css": {
        ("box-shadow", "0 20px 54px rgba(28, 36, 44, .16), inset 0 1px 0 rgba(255, 255, 255, .80), 0 0 0 1px var(--inset-veil-mist) !important"): 1,
    },
    "padiem-settings.css": {
        # background mist 1선언(glass 닫기 단추)은 #8001(대표 11-18 08:38)로
        # 칸 바탕 var(--card-bg) 한 판 토큰이 되며 선언 자체가 사라졌다.
        ("border-color", "var(--line-veil-mist)"): 1,
    },
    "shared-tooltip.css": {
        ("border", "1px solid var(--line-veil-mist)"): 1,
    },
}

LITERALS = ("rgba(255, 255, 255, .34)", "rgba(255,255,255,.34)")


def test_root_tokens_hold_the_pre_change_literal() -> None:
    rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
    root = next(r for r in rules if r.media is None and ":root" in r.selectors)
    for name, literal in ROOT_TOKENS.items():
        assert root.declarations.get(name) == literal, name


def test_no_theme_block_overrides_the_tokens() -> None:
    for rule in parse_rules(TOKENS.read_text(encoding="utf-8")):
        themed = rule.media is not None or any("data-theme" in s for s in rule.selectors)
        if themed:
            for name in ROOT_TOKENS:
                assert name not in rule.declarations, (rule.selectors, name)


def test_the_twelve_declarations_consume_the_right_role() -> None:
    total = 0
    for sheet, expected in CHANGED.items():
        actual: Counter = Counter()
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                normalized = re.sub(r"\s+", " ", value).strip()
                if any(name in normalized for name in ROOT_TOKENS):
                    actual[(prop, normalized)] += 1
        assert actual == Counter(expected), sheet
        total += sum(actual.values())
    assert total == 12


def test_swapping_the_tokens_back_returns_the_original_literal() -> None:
    for sheet, expected in CHANGED.items():
        for (prop, value) in expected:
            restored = value
            for name, literal in ROOT_TOKENS.items():
                restored = restored.replace(f"var({name})", literal)
            assert any(literal in restored for literal in LITERALS), (sheet, prop, value)


def test_no_mist_literal_remains_in_the_changed_sheets() -> None:
    for sheet in CHANGED:
        text = (STATIC / sheet).read_text(encoding="utf-8")
        for literal in LITERALS:
            assert literal not in text, (sheet, literal)


def test_each_token_stays_in_its_own_property_family() -> None:
    for sheet in CHANGED:
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                if "--surface-veil-mist" in value:
                    assert prop.startswith("background"), (sheet, prop)
                if "--text-veil-mist" in value:
                    assert prop == "color", (sheet, prop)
                if "--line-veil-mist" in value:
                    assert prop.startswith("border"), (sheet, prop)
                if "--inset-veil-mist" in value:
                    assert prop.startswith("box-shadow"), (sheet, prop)


def test_consumers_load_tokens_first() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for sheet in CHANGED:
        link = "./" + sheet
        assert link in index, sheet
        assert index.index("padiem-tokens.css") < index.index(link), sheet


def test_sidebar_sheets_and_glass_sheet_stay_out() -> None:
    for sheet in ("padiem-glass.css", "sidebar-unified.css", "sidebar-utility.css"):
        text = (STATIC / sheet).read_text(encoding="utf-8")
        for name in ROOT_TOKENS:
            assert name not in text, (sheet, name)
