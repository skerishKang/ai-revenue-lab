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
        roots = [r for r in rules if r.selectors == [":root"]]
        self.assertEqual(len(roots), 1, "one :root block carries the defaults")
        props = _custom_properties(roots[0])
        for name, number in PRIMARY_NUMBERS.items():
            self.assertEqual(props.get(name), number, name)
        # #7187 R3 2차: the line / input-border / focus-ring / surface-border
        # tokens joined the same file; their values are pinned by
        # test_261109_line_input_focus_tokens_7187.py.
        # #7187 R3 3차: the accent family and --card-border joined too;
        # their values are pinned by test_261109_card_accent_tokens_7187.py.
        self.assertEqual(
            set(props),
            set(PRIMARY_NUMBERS)
            | {"--line", "--input-border-strong", "--focus-ring", "--surface-border"}
            | {"--accent", "--accent-contrast", "--accent-soft", "--accent-strong",
               "--card-border"},
            "no stray token: the file holds the documented families only")

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
