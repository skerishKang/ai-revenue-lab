"""#7187 R3 4차 — PC 연결 클러스터의 지역 값을 토큰 파일 한 곳에.

1차(#7256) 주요 버튼, 2차(#7263) 선·입력칸·포커스, 3차(#7277) 카드 테두리·accent
계열에 이어, 4차는 PC 연결 화면 가족을 다룬다:

* ``pc-pairing-card.css`` / ``pc-connect-flow.css`` / ``claw-device-manager.css`` /
  ``claw-device-guidance.css`` / ``claw-local-handoff.css`` /
  ``claw-composer-connection-status.css`` / ``claw-pc-enrollment-consent.css``
* 이 가족은 전역 시맨틱 토큰(--muted/--text/--panel/--success/--danger)을
  ``var(--token, 숫자)`` fallback으로 소비하고 있었다. 토큰은 항상 정의되므로
  fallback은 죽은 코드이고, 제거해도 화면 결과가 바뀌지 않는다.
* 나머지 값은 ``var(--surface, …)`` / ``var(--text-dim, …)`` / ``var(--focus, …)``
  / ``var(--warning, …)`` / ``var(--surface-2, …)`` / ``var(--border, …)``
  fallback으로 숨어 있었다. 이름 없는 fallback은 이름을 주면 다른 시트의
  같은 이름 fallback까지 함께 바뀌므로(def 2차의 --border 판정), 이 가족 전용
  이름(--pc-* / --claw-local-*)으로 옮겼다.
* dark에서 컴포넌트 스코프가 실제로 덮어쓰던 값(─surface #202b3c,
  --claw-local 표면 rgba(255,255,255,.06), --text-dim #b8c5d4/#d1d5db)만
  토큰 파일의 dark 블록이 소유한다. 그 결과 각 시트의 dark 블록에서
  --surface/--text-dim 정의가 사라지고, 실제로 다른 --text/--line/--muted만 남는다.

토큰화로 필요 없어진 ``!important``는 없다. 이 가족의 ``!important``는
``display: none``·``prefers-reduced-motion``·frozen styles.css/테마 시트의
composer padding을 이기는 cascade 사유이며, 값 토큰과 무관하다(아래 시험이
그대로 남아 있음을 확인한다).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from css_rules import parse_rules, find_rules_with_selector, declaration

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

TOKENS = STATIC / "padiem-tokens.css"

CLUSTER = (
    "pc-pairing-card.css",
    "pc-connect-flow.css",
    "claw-device-manager.css",
    "claw-device-guidance.css",
    "claw-local-handoff.css",
    "claw-composer-connection-status.css",
    "claw-pc-enrollment-consent.css",
)

#: :root 기본값(측정값 그대로). 이 값들은 이전에는 각 시트의 fallback이었다.
BASE_VALUES = {
    "--pc-focus": "#2a7db4",
    "--pc-warning": "#8a5a00",
    "--pc-ack-surface": "rgba(238,243,247,.6)",
    "--pc-connect-surface": "#f7f8fa",
    "--pc-consent-veil": "rgba(255,255,255,.76)",
    "--pc-consent-panel": "rgba(255,255,255,.86)",
    "--pc-device-veil": "rgba(255,255,255,.76)",
    "--pc-device-panel": "rgba(255,255,255,.86)",
    "--pc-device-solid": "#fff",
    "--pc-device-tint": "rgba(250,253,255,.5)",
    "--pc-text-dim": "#506a7b",
    "--pc-text-dim-soft": "#607a89",
    "--pc-text-dim-muted": "#536e80",
    "--pc-consent-text-dim": "#506a7b",
    "--claw-local-focus": "#2563eb",
    "--claw-local-surface": "rgba(255,255,255,.72)",
    "--claw-local-surface-ghost": "transparent",
    "--claw-local-text-dim": "#374151",
    "--claw-local-border": "rgba(150,160,180,.35)",
    "--claw-local-border-strong": "rgba(150,160,180,.45)",
    "--claw-local-border-soft": "rgba(0,0,0,.14)",
}

#: dark에서 실제로 달라지던 값만 dark 블록이 덮어쓴다(#6694/#3084 측정값).
DARK_VALUES = {
    "--pc-device-veil": "#202b3c",
    "--pc-device-panel": "#202b3c",
    "--pc-device-solid": "#202b3c",
    "--pc-device-tint": "#202b3c",
    "--pc-text-dim": "#b8c5d4",
    "--pc-text-dim-soft": "#b8c5d4",
    "--pc-text-dim-muted": "#b8c5d4",
    "--claw-local-surface": "rgba(255,255,255,.06)",
    "--claw-local-surface-ghost": "rgba(255,255,255,.06)",
    "--claw-local-text-dim": "#d1d5db",
}

#: dark에 덮어쓰기가 없어 기본값이 그대로 적용되는 토큰(동작 고정).
DARK_UNOVERRIDDEN = {
    "--pc-focus", "--pc-warning", "--pc-ack-surface", "--pc-connect-surface",
    "--pc-consent-veil", "--pc-consent-panel", "--pc-consent-text-dim",
    "--claw-local-focus", "--claw-local-border", "--claw-local-border-strong",
    "--claw-local-border-soft",
}

#: 레이아웃 런타임 값 — 팔레트가 아니므로 fallback을 유지한다.
LAYOUT_FALLBACKS = {
    "--padiem-composer-clearance", "--padiem-visual-keyboard-inset",
    "--composer-pc-status-gutter",
}


def _custom_properties(block) -> dict[str, str]:
    return {name: value for name, value in block.declarations.items()
            if name.startswith("--")}


def _theme_block(text: str, theme: str) -> str:
    m = re.search(r'html\[data-theme="%s"\] \{' % re.escape(theme), text)
    assert m is not None, theme
    return text[m.end(): text.index("\n}", m.end())]


def _scoped_dark_block(text: str) -> str:
    """컴포넌트 스코프의 dark 블록(:root[data-theme="dark"] .claw-…)."""
    m = re.search(r':root\[data-theme="dark"\][^{]*\{', text)
    assert m is not None, "dark scope"
    return text[m.end(): text.index("}", m.end())]


def _rule_with(source_rules, selector: str, prop: str):
    blocks = find_rules_with_selector(source_rules, selector)
    for rule in blocks:
        if declaration(rule, prop) is not None:
            return rule
    raise AssertionError(f"{selector} has no {prop} declaration")


def _all_fallbacks(source: str) -> list[tuple[str, str]]:
    return re.findall(r'var\(\s*(--[a-zA-Z0-9-]+)\s*,\s*([^()]*(?:\([^()]*\)[^()]*)*)\)',
                      source)


class TestPcClusterTokens(unittest.TestCase):
    def test_the_token_file_defines_the_cluster_family(self) -> None:
        rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
        roots = [r for r in rules if r.selectors == [":root"]]
        self.assertEqual(len(roots), 1)
        props = _custom_properties(roots[0])
        for name, value in BASE_VALUES.items():
            self.assertEqual(props.get(name), value, name)

        text = TOKENS.read_text(encoding="utf-8")
        dark = _theme_block(text, "dark")
        for name, value in DARK_VALUES.items():
            self.assertRegex(dark, rf'{re.escape(name)}:\s*{re.escape(value)};', name)
        for name in DARK_UNOVERRIDDEN:
            self.assertNotIn(name + ":", dark, f"{name} must keep its base value in dark")

    def test_no_other_sheet_owns_the_cluster_tokens(self) -> None:
        """테마/컴포넌트 시트가 이 토큰을 다시 정의하면 소유권이 갈라진다."""
        names = set(BASE_VALUES) | set(DARK_VALUES)
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS:
                continue
            for rule in parse_rules(sheet.read_text(encoding="utf-8")):
                for name, value in rule.declarations.items():
                    if name in names:
                        offenders.append((sheet.name, name, value))
        self.assertEqual(offenders, [], offenders)

    def test_the_cluster_has_no_token_fallbacks(self) -> None:
        """전역 토큰과 클러스터 토큰은 항상 정의되므로 fallback을 쓰지 않는다.

        예외는 레이아웃 런타임 값뿐이다(팔레트 아님, LAYOUT_FALLBACKS).
        """
        offenders = []
        for name in CLUSTER:
            source = (STATIC / name).read_text(encoding="utf-8")
            for token, fallback in _all_fallbacks(source):
                if token in LAYOUT_FALLBACKS:
                    continue
                offenders.append((name, token, fallback.strip()[:50]))
        self.assertEqual(offenders, [], offenders)

    def test_the_cluster_consumes_the_global_semantic_tokens(self) -> None:
        """1차 정리: 죽은 fallback이 사라지고 토큰 이름만 남는다."""
        for name in CLUSTER:
            source = (STATIC / name).read_text(encoding="utf-8")
            for token in ("--muted", "--text", "--panel", "--success", "--danger"):
                self.assertNotIn(f"var({token},", source, f"{name}: {token} fallback")

    def test_the_representative_rules_name_the_tokens(self) -> None:
        pairing = parse_rules((STATIC / "pc-pairing-card.css").read_text(encoding="utf-8"))
        help_text = _rule_with(pairing, ".pc-pairing-help", "color")
        self.assertEqual(declaration(help_text, "color"), "var(--muted)")
        steps = _rule_with(pairing, ".pc-pairing-steps", "background")
        self.assertEqual(declaration(steps, "background"), "var(--panel)")

        flow = parse_rules((STATIC / "pc-connect-flow.css").read_text(encoding="utf-8"))
        modal = _rule_with(flow, ".pc-connect-modal", "background")
        self.assertEqual(declaration(modal, "background"), "var(--panel)")
        drives = _rule_with(flow, ".pc-connect-popover-drives", "background")
        self.assertEqual(declaration(drives, "background"), "var(--pc-connect-surface)")

        manager = parse_rules((STATIC / "claw-device-manager.css").read_text(encoding="utf-8"))
        toggle = _rule_with(manager, ".claw-device-manager-toggle", "background")
        self.assertEqual(declaration(toggle, "background"), "var(--pc-device-veil)")
        panel = _rule_with(manager, ".claw-device-manager-panel", "background")
        self.assertEqual(declaration(panel, "background"), "var(--pc-device-panel)")
        select = _rule_with(manager, ".claw-device-manager-select", "background")
        self.assertEqual(declaration(select, "background"), "var(--pc-device-solid)")

        guidance = parse_rules((STATIC / "claw-device-guidance.css").read_text(encoding="utf-8"))
        gpanel = _rule_with(guidance, ".claw-device-guidance-panel", "background")
        self.assertEqual(declaration(gpanel, "background"), "var(--pc-device-panel)")

        consent = parse_rules((STATIC / "claw-pc-enrollment-consent.css").read_text(encoding="utf-8"))
        ctoggle = _rule_with(consent, ".claw-pc-consent-toggle", "background")
        self.assertEqual(declaration(ctoggle, "background"), "var(--pc-consent-veil)")
        ack = _rule_with(consent, ".claw-pc-consent-ack", "background")
        self.assertEqual(declaration(ack, "background"), "var(--pc-ack-surface)")

        handoff = parse_rules((STATIC / "claw-local-handoff.css").read_text(encoding="utf-8"))
        local = _rule_with(handoff, ".claw-local", "background")
        self.assertEqual(declaration(local, "background"), "var(--claw-local-surface)")
        choice = _rule_with(handoff, ".claw-office-choice", "background")
        self.assertEqual(declaration(choice, "background"),
                         "var(--claw-local-surface-ghost)")
        approval = _rule_with(handoff, ".claw-web-office-approval", "border-top")
        self.assertEqual(declaration(approval, "border-top"),
                         "1px solid var(--claw-local-border)")

        status = (STATIC / "claw-composer-connection-status.css").read_text(encoding="utf-8")
        self.assertIn("background: var(--pc-warning);", status)
        self.assertIn("background: var(--success);", status)
        self.assertIn("background: var(--danger);", status)

    def test_the_component_dark_scopes_keep_only_real_overrides(self) -> None:
        """토큰화 후에도 실제로 다른 값(--text/--line/--muted)은 지역 결정으로 남는다."""
        manager = (STATIC / "claw-device-manager.css").read_text(encoding="utf-8")
        guidance = (STATIC / "claw-device-guidance.css").read_text(encoding="utf-8")
        handoff = (STATIC / "claw-local-handoff.css").read_text(encoding="utf-8")

        for source in (manager, guidance):
            block = _scoped_dark_block(source)
            self.assertIn("--text: #e7eef6;", block)
            self.assertIn("--line: rgba(218,231,247,.2);", block)
            self.assertNotIn("--surface", block)
            self.assertNotIn("--text-dim", block)

        block = _scoped_dark_block(handoff)
        self.assertIn("--line: rgba(255, 255, 255, 0.16);", block)
        self.assertIn("--muted: #9ca3af;", block)
        self.assertNotIn("--surface", block)
        self.assertNotIn("--text-dim", block)

    def test_functional_important_flags_are_unchanged(self) -> None:
        """!important는 토큰과 무관한 기능/캐스케이드 사유로 그대로 남는다."""
        manager = (STATIC / "claw-device-manager.css").read_text(encoding="utf-8")
        guidance = (STATIC / "claw-device-guidance.css").read_text(encoding="utf-8")
        handoff = (STATIC / "claw-local-handoff.css").read_text(encoding="utf-8")
        status = (STATIC / "claw-composer-connection-status.css").read_text(encoding="utf-8")

        self.assertIn("display: none !important;", manager)
        self.assertIn("display: none !important;", guidance)
        self.assertIn("transition: none !important;", manager)
        self.assertIn("transition: none !important;", guidance)
        self.assertIn("transition: none !important;", handoff)
        self.assertIn("transition: none !important;", status)
        # frozen styles.css/테마 시트의 composer padding을 이기는 규칙.
        self.assertIn("padding-right: var(--composer-pc-status-gutter, 0px) !important;",
                      status)


if __name__ == "__main__":
    unittest.main()
