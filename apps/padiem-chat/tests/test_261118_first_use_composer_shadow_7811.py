"""#7811 C2 — 첫 화면 입력창 그림자를 쓰임새 토큰으로.

padiem-first-use.css의 `.app-shell[data-state="home"] .composer` box-shadow
3겹(안쪽 흰 하이라이트·바깥 검정 그림자·파란 링)을
padiem-tokens.css의 --composer-home-shadow 하나로 옮긴다.

값은 치환 전 사용처 리터럴 그대로다. 이 그림자는 모든 테마에서 같은 값이라
:root에만 두고, dark·glass·시스템 다크 블록은 덮지 않는다. glass에서는
padiem-glass-brand-polish.css의 같은 값 핀이 실제로 칠해지므로, 이 토큰은
light·dark·cinematic·padiem-home의 홈 입력창을 소유한다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.token_sheets_source import first_use_css, history_css, index_html, read, read_static, tokens_css

import re
from pathlib import Path

from css_rules import declaration, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"
FIRST_USE = STATIC / "padiem-first-use.css"

TOKEN = "--composer-home-shadow"
VALUE = (
    "inset 0 1px 0 rgba(255, 255, 255, .07), "
    "0 22px 64px rgba(0, 0, 0, .22), "
    "0 0 0 1px rgba(136, 201, 255, .035)"
)
HOME_SELECTOR = '.app-shell[data-state="home"] .composer'


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _rules(path: Path):
    return parse_rules(read(path))


def _root(rules) -> dict[str, str]:
    roots = [r for r in rules if r.selectors == [":root"] and r.media is None]
    assert len(roots) == 1
    return roots[0].declarations


def test_root_token_holds_the_pre_change_shadow() -> None:
    root = _root(_rules(TOKENS))
    assert _norm(root.get(TOKEN, "")) == _norm(VALUE)


def test_no_theme_block_overrides_the_home_shadow() -> None:
    rules = _rules(TOKENS)
    for rule in rules:
        if rule.selectors == [":root"] and rule.media is None:
            continue
        assert TOKEN not in rule.declarations, rule.selectors


def test_first_use_composer_consumes_only_the_token() -> None:
    rules = _rules(FIRST_USE)
    matches = [
        r for r in rules
        if r.media is None and HOME_SELECTOR in r.selectors
    ]
    assert len(matches) == 1
    rule = matches[0]
    assert declaration(rule, "box-shadow") == f"var({TOKEN})"
    assert declaration(rule, "border-color") == "var(--line-veil-faint)"


def test_first_use_has_no_color_literals_left_for_the_home_composer() -> None:
    rules = _rules(FIRST_USE)
    for rule in rules:
        if HOME_SELECTOR not in rule.selectors:
            continue
        for prop, value in rule.declarations.items():
            assert re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", value) is None, (prop, value)
    text = first_use_css()
    assert "inset 0 1px 0 rgba(255, 255, 255, .07)" not in text
    assert "0 22px 64px rgba(0, 0, 0, .22)" not in text
    assert "0 0 0 1px rgba(136, 201, 255, .035)" not in text
