"""#8022 — glass 연결 화면(앱 연결) 카드 경계 계약.

glass 연결 화면의 카드 경계는 흰 판 위에서 사실상 보이지 않았다(잉크 .14 ≈
1.2:1, 감사 261119). 수정: glass에서만 기존 잉크 토큰(--text-deep-ink)에서
파생한 헤어라인(color-mix 50%)으로 경계를 뚜렷하게 한다 — 새 리터럴 없음,
다른 테마의 기존 .14 경계는 그대로다. 카드 안 글자(#3d4c59·태그라인)는
실측 4.5:1 이상이라 그대로 둔다.
"""

from __future__ import annotations

from pathlib import Path

from css_rules import declaration, parse_rules

STATIC = Path(__file__).resolve().parents[1] / "static"
STANDALONE_CSS = (STATIC / "standalone-views.css").read_text(encoding="utf-8")
CAPABILITY_CSS = (STATIC / "capability-nav.css").read_text(encoding="utf-8")

MIX = "color-mix(in srgb, var(--text-deep-ink) 50%, transparent)"


def _rules(css: str):
    return parse_rules(css)


def _glass_scoped(rules: list, suffix: str, label: str):
    matched = [rule for rule in rules
               if rule.media is None
               and any(selector.endswith(suffix)
                       and selector.startswith('html[data-theme="padiem-glass"]')
                       for selector in rule.selectors)]
    assert len(matched) == 1, f"{label}: glass 스코프 규칙 1개, 실제 {len(matched)}개"
    return matched[0]


def test_glass_connector_cards_have_a_visible_ink_border() -> None:
    rules = _rules(STANDALONE_CSS)
    for suffix, label in [
        ("#connectorsViewBody .capability-card", "연결 카드"),
        ("#connectorsViewBody .connector-retry", "재시도 단추"),
    ]:
        rule = _glass_scoped(rules, suffix, label)
        assert _mix(rule) == MIX, label


def test_glass_connector_dialog_mirror_matches_the_view() -> None:
    rules = _rules(CAPABILITY_CSS)
    for suffix, label in [
        ("#connectorsDialog .capability-card", "연결 카드(다이얼로그)"),
        ("#connectorsDialog .connector-retry", "재시도 단추(다이얼로그)"),
    ]:
        rule = _glass_scoped(rules, suffix, label)
        assert _mix(rule) == MIX, label


def test_other_themes_keep_the_original_hairline() -> None:
    """glass가 아닌 테마의 기존 .14/.16 경계는 그대로다(감사 기준 '정상')."""
    rules = _rules(STANDALONE_CSS)
    card = [rule for rule in rules
            if rule.media is None
            and rule.selectors == ["#connectorsViewBody .capability-card"]]
    assert len(card) == 1
    assert declaration(card[0], "border-color") == "rgba(23, 33, 42, 0.14)"


def _mix(rule):
    raw = declaration(rule, "border-color")
    assert raw is not None, "border-color 선언이 없다"
    return raw.replace("!important", "").strip()
