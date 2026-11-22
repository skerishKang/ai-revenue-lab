"""#7187 R3 — the primary navy lives in one token file.

대표 결정 #7162 put one shared primary rule in the override layer; the same
four numbers were still pasted as literals across voice-composer.css,
voice-ui.css, meeting-capture.css and help.css. This pins the R3 tokenization
step: the numbers exist only in ``padiem-tokens.css``, every consumer names
the token, and the token file is loaded ahead of the sheets that read it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from css_rules import parse_rules, find_rules_with_selector, declaration

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

TOKENS = STATIC / "padiem-tokens.css"

#: The shared primary family (#7162 대표 결정): fill, border, hover pair and
#: the focus ring. Measured identical in every theme, so the token file keeps
#: one default and no per-theme override.
PRIMARY_NUMBERS = {
    "--primary-bg": "#355977",
    "--primary-border": "#294b64",
    "--primary-hover-bg": "#2e4d67",
    "--primary-hover-border": "#23445d",
    "--primary-focus": "#6a9abc",
}

RAW_NUMBERS = tuple(PRIMARY_NUMBERS.values())


def _custom_properties(block) -> dict[str, str]:
    return {name: value for name, value in block.declarations.items()
            if name.startswith("--")}


class TestPrimaryTokens(unittest.TestCase):
    def test_the_token_file_defines_exactly_the_shared_numbers(self) -> None:
        rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
        roots = [r for r in rules if r.selectors == [":root"] and r.media is None]
        self.assertEqual(len(roots), 1, "one :root block carries the defaults")
        props = _custom_properties(roots[0])
        for name, number in PRIMARY_NUMBERS.items():
            self.assertEqual(props.get(name), number, name)
        # #7187 R3 2차: the line / input-border / focus-ring / surface-border
        # tokens joined the same file; their values are pinned by
        # test_261109_line_input_focus_tokens_7187.py.
        # #7187 R3 3차: the accent family and --card-border joined too;
        # their values are pinned by test_261109_card_accent_tokens_7187.py.
        # #7187 R3 4차: the PC connection cluster's local palette joined;
        # its values are pinned by test_261111_pc_cluster_tokens_7187.py.
        self.assertEqual(
            set(props),
            set(PRIMARY_NUMBERS)
            | {"--sidebar-control-inset", "--sidebar-control-radius",
               "--sidebar-control-height"}
            | {"--line", "--input-border-strong", "--focus-ring", "--surface-border"}
            | {"--accent", "--accent-contrast", "--accent-soft", "--accent-strong",
               "--card-border"}
            | {"--pc-focus", "--pc-warning", "--pc-ack-surface",
               "--pc-connect-surface", "--pc-consent-veil", "--pc-consent-panel",
               "--pc-device-veil", "--pc-device-panel", "--pc-device-solid",
               "--pc-device-tint", "--pc-text-dim", "--pc-text-dim-soft",
               "--pc-text-dim-muted", "--pc-consent-text-dim",
               "--claw-local-focus", "--claw-local-surface",
               "--claw-local-surface-ghost", "--claw-local-text-dim",
               "--claw-local-border", "--claw-local-border-strong",
               "--claw-local-border-soft"}
            # #7817: the first screen's second headline line reads one theme
            # token; its defaults and per-theme values are pinned by
            # test_7817_first_screen_contrast.py.
            | {"--hero-sub-color"}
            # #7829: the code header (language label, copy button) reads
            # two theme tokens; their defaults and per-theme values are
            # pinned by test_7829_code_header_contrast.py.
            | {"--code-header-text", "--code-header-button-text"}
            | {"--radius-xs", "--radius-sm", "--radius-lg", "--radius-pill",
               "--radius-circle"}
            # #7187 1차(261118): the white veil role/intensity tokens joined;
            # their values are pinned by test_261118_white_veil_tokens_7187.py.
            | {"--surface-veil-faint", "--surface-veil-soft", "--surface-veil-strong",
               "--line-veil-faint", "--line-veil-soft", "--line-veil-strong"}
            # #7187 2차(261118): the white text-veil tokens joined; their
            # values are pinned by test_261118_white_veil_text_tokens_7187.py.
            | {"--text-veil-faint", "--text-veil-strong"}
            # #7187 3차: 아주 옅은 칸 바탕 씻김과 얇은 상단 하이라이트 선.
            | {"--surface-veil-ghost", "--inset-veil-ghost"}
            # #7187 4차: 패널면 씻김과 패널 상단 하이라이트 선.
            | {"--surface-veil-panel", "--inset-veil-panel"}
            # #7187 5차: 엷은 구분선·칸 바탕·인셋 하이라이트.
            | {"--line-veil-dim", "--surface-veil-dim", "--inset-veil-dim"}
            # #7187 6차: 짙은 남 잉크(글자/선택 칸) 역할 토큰.
            | {"--text-deep-ink", "--swatch-deep-ink"}
            # #7187 7차: 옅은 안개(면·글자·선·하이라이트) 역할 토큰.
            | {"--surface-veil-mist", "--text-veil-mist", "--line-veil-mist",
               "--inset-veil-mist"}
            # #7187 8차: 옅은 흰 안개(면·선·글자) 역할 토큰.
            | {"--surface-veil-haze", "--line-veil-haze", "--text-veil-haze"}
            # #7187 9차: 유리 패널·대화상자·설정 머리 글자의 짙은 잉크.
            # 값·소비 선언은 test_261119_panel_ink_tokens_7187.py가 고정한다.
            | {"--text-panel-ink"}
            # #7811 C2(261118): history.css 바탕 색 토큰이 가족으로 합류했다.
            # --dialog-dim은 #5666 공유 대화상자 딤(padiem-settings.css가 같은
            # 값을 쓴다). 값들은 test_261118_history_bg_tokens_7811.py가 고정.
            | {"--dialog-dim", "--control-wash-faint", "--control-wash-soft",
               "--control-wash-strong", "--control-wash-hover",
               "--danger-wash-soft", "--danger-wash-strong",
               # #7811 C2b(261118): 로그인 창 패널·주 단추 쓰임새 토큰.
               # 값·테마 덮개·시스템 다크 분기는
               # test_261118_auth_panel_tokens_7811.py가 고정한다.
               "--auth-panel-bg", "--auth-panel-text", "--auth-panel-border",
               "--auth-primary-bg", "--auth-primary-text",
               # #7811 C2(261118): 첫 화면 입력창 그림자 쓰임새 토큰.
               # 값은 test_261118_first_use_composer_shadow_7811.py가 고정한다.
               "--composer-home-shadow",
               # #7811 C2 foundation(261118): 바탕·크롬 색 토큰. 값·테마
               # 덮개·소비 선언은
               # test_261118_foundation_chrome_tokens_7811.py가 고정한다.
               "--app-root-bg", "--app-grid-line", "--app-grid-fade",
               "--app-selection-text", "--app-selection-bg",
               "--app-focus-outline", "--brand-mark-glow",
               "--side-icon-text", "--sidebar-footer-border",
               # #8020(261118): Claw 요청 말풍선 글자·배경. 값·테마 덮개·
               # 소비 선언은 test_8020_claw_bubble_contrast.py가 고정한다.
               "--claw-request-bubble-text", "--claw-request-bubble-bg",
               # #8024: usage tokens for theme-agnostic panel skins.
               "--surface-panel-deep",
               "--surface-panel-solid",
               "--surface-panel-dim",
               "--surface-card-deep",
               "--surface-card-solid",
               "--surface-panel-veil",
               "--surface-ink-deep",
               "--surface-fade-deep",
               "--surface-fade-solid",
               "--panel-text-faint",
               "--panel-text-soft",
               "--panel-text-strong",
               "--panel-text-max",
               # #7811 C2 calendar(261122): calendar.css 고정 팔레트 색 토큰.
               # 값·소비 선언은 test_261122_calendar_palette_tokens_7811.py가 고정.
               "--calendar-paper", "--calendar-error-border", "--calendar-error-bg",
               "--calendar-error-compact-bg", "--calendar-error-compact-border",
               "--calendar-error-text", "--calendar-status-invalid-text",
               "--calendar-delete-text", "--calendar-item-type-bg",
               "--calendar-submit-bg", "--calendar-nav-current-bg",
               "--calendar-focus-outline", "--calendar-editor-outline",
               "--calendar-today-text", "--calendar-visual-border",
               "--calendar-visual-bg", "--calendar-weekday-bg",
               "--calendar-weekday-border", "--calendar-weekday-text",
               "--calendar-grid-bg", "--calendar-day-text",
               "--calendar-day-outside-text", "--calendar-event-bg",
               "--calendar-event-text", "--calendar-worklog-bg",
               "--calendar-worklog-text", "--calendar-alert-bg",
               "--calendar-alert-text", "--calendar-more-text",
               "--calendar-week-date-text", "--calendar-allday-bg",
               "--calendar-allday-border", "--calendar-allday-label-text",
               "--calendar-hour-border", "--calendar-hour-label-text",
               "--calendar-overlay-border", "--calendar-overlay-bg",
               "--calendar-overlay-shadow", "--calendar-editor-border",
               "--calendar-editor-bg", "--calendar-editor-text",
               "--calendar-unknown-type-bg",
               },
            "no stray token: the file holds the documented families only")
        # #7187 반경 스케일(261115): the border-radius scale joined the token
        # file; its values are the replaced use-site values, pinned here.
        for name, value in (("--radius-xs", "8px"), ("--radius-sm", "10px"),
                            ("--radius-lg", "20px"), ("--radius-pill", "999px"),
                            ("--radius-circle", "50%")):
            self.assertEqual(props.get(name), value, name)

    def test_no_other_sheet_carries_the_primary_numbers(self) -> None:
        """The completion criterion: the numbers exist in one file only.

        Read through the css_rules helper (#7186), so a number inside a
        comment or a selector does not count — only a declaration that would
        actually paint does.
        """
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS:
                continue
            for rule in parse_rules(sheet.read_text(encoding="utf-8")):
                for name, value in rule.declarations.items():
                    if any(number in value for number in RAW_NUMBERS):
                        offenders.append((sheet.name, name, value))
        self.assertEqual(offenders, [], offenders)

    def test_the_shared_primary_rule_names_the_tokens(self) -> None:
        polish = parse_rules((STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8"))
        blocks = find_rules_with_selector(polish, ".claw-generate-button")
        self.assertEqual(len(blocks), 3, "base, hover and focus-visible")
        base = next(r for r in blocks
                    if not any(s.endswith((":hover", ":focus-visible"))
                               for s in r.selectors))
        hover = next(r for r in blocks
                     if any(s.endswith(":hover") for s in r.selectors))
        focus = next(r for r in blocks
                     if any(s.endswith(":focus-visible") for s in r.selectors))
        self.assertEqual(declaration(base, "background"), "var(--primary-bg)")
        self.assertEqual(declaration(base, "border-color"), "var(--primary-border)")
        self.assertEqual(declaration(hover, "background"), "var(--primary-hover-bg)")
        self.assertEqual(declaration(hover, "border-color"), "var(--primary-hover-border)")
        self.assertEqual(declaration(focus, "outline"), "3px solid var(--primary-focus)")

    def test_the_composer_send_button_names_the_tokens(self) -> None:
        composer = parse_rules((STATIC / "voice-composer.css").read_text(encoding="utf-8"))
        send = [r for r in composer
                if any("#composerForm .send-button" == s for s in r.selectors)
                or any(s.startswith("#composerForm .send-button:") for s in r.selectors)]
        base = next(r for r in send
                    if all(":" not in s for s in r.selectors))
        self.assertEqual(declaration(base, "background"), "var(--primary-bg)")
        self.assertEqual(declaration(base, "border"), "1px solid var(--primary-border)")
        hover = next(r for r in send if any(s.endswith(":hover") for s in r.selectors))
        self.assertEqual(declaration(hover, "background"), "var(--primary-hover-bg)")
        self.assertEqual(declaration(hover, "border-color"), "var(--primary-hover-border)")
        focus = next(r for r in send if any(s.endswith(":focus-visible") for s in r.selectors))
        self.assertEqual(declaration(focus, "outline"), "3px solid var(--primary-focus)")
        # The legacy white-fill override keeps its !important (it beats the
        # frozen styles.css copy, a specificity reason unrelated to tokens).
        override = next(r for r in send
                        if any(s.endswith(":not(:disabled)") for s in r.selectors))
        self.assertEqual(declaration(override, "background"),
                         "var(--primary-bg) !important")

    def test_help_pages_alias_the_tokens_without_a_second_copy(self) -> None:
        help_css = parse_rules((STATIC / "help.css").read_text(encoding="utf-8"))
        body = find_rules_with_selector(help_css, ".chat-help-body")
        self.assertEqual(len(body), 1)
        props = _custom_properties(body[0])
        self.assertEqual(props.get("--help-navy"), "var(--primary-bg)")
        self.assertEqual(props.get("--help-navy-line"), "var(--primary-border)")
        self.assertEqual(props.get("--help-navy-hover"), "var(--primary-hover-bg)")
        self.assertEqual(props.get("--help-focus"), "var(--primary-focus)")

    def test_every_consuming_page_loads_the_token_file(self) -> None:
        for page in ("index.html", "help.html", "install.html"):
            html = (STATIC / page).read_text(encoding="utf-8")
            links = re.findall(r'<link rel="stylesheet" href="\./([^"]+\.css)"', html)
            self.assertIn("padiem-tokens.css", links, page)
            self.assertLess(links.index("padiem-tokens.css"),
                            next(i for i, name in enumerate(links)
                                 if name in ("padiem-chat-ui-polish.css", "help.css")),
                            f"{page}: tokens must load before their consumers")


if __name__ == "__main__":
    unittest.main()
