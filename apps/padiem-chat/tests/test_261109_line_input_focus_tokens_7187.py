"""#7187 R3 2차 — 선·입력칸 테두리·포커스 색도 토큰 파일 한 곳에.

1차(#7256)가 주요 버튼 남색을 모았다면 2차는 같은 방식을 선(구분선·테두리)과
입력칸 테두리·포커스 색에 적용한다:

* ``--line`` / ``--input-border-strong`` / ``--focus-ring`` 은 원래
  padiem-themes.css(와 padiem-glass.css, padiem-dark-contrast.css)가 테마별로
  정의했다. 값은 그대로 옮기고 정의는 padiem-tokens.css 한 곳에만 둔다.
* 설정 화면 입력칸·카드 테두리(#ccd2d8)는 정의되지 않은 ``--border``의
  fallback으로 살아 있었다. 새 이름 ``--surface-border`` 로 토큰화한다.
* 토큰이 항상 정의되므로 소비 규칙은 fallback 없이 쓴다. 기존
  ``var(--line, 숫자)`` fallback은 화면 결과를 바꾸지 않고 제거했다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from css_rules import parse_rules, find_rules_with_selector, declaration

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

TOKENS = STATIC / "padiem-tokens.css"
FROZEN = {"styles.css"}  # 바이트 고정 참조 미러 — 이 PR의 대상이 아니다.

#: 토큰 파일이 소유하는 값. 테마 블록과 :root 기본값 모두 여기서 온다.
LINE_VALUES = {
    "light": "#e3e3e9",
    "dark": "#405365",  # padiem-dark-contrast.css가 덮어쓰던 실제 값
    "cinematic": "rgba(255,255,255,.14)",
    "padiem-home": "rgba(26,34,48,.12)",
    "padiem-glass": "rgba(255, 255, 255, .38)",
}
INPUT_BORDER_VALUES = {
    "light": "#767e8a",
    "dark": "rgba(255,255,255,.45)",
    "cinematic": "rgba(255,255,255,.45)",
    "padiem-home": "#767e8a",
    "padiem-glass": "#56616b",
}
FOCUS_VALUES = {
    "light": "rgba(101, 87, 232, .24)",
    "dark": "rgba(159,192,221,.32)",
    "cinematic": "rgba(136,201,255,.70)",
    "padiem-home": "rgba(58,123,213,.28)",
    "padiem-glass": "rgba(121, 188, 231, .42)",
}
SURFACE_BORDER = "#ccd2d8"

#: 자동 검사에서 너무 흔한 반투명 백색은 제외한다 — 시네마틱/글래스 인접
#: 시트가 구성 요소 지역 값으로 같은 흰색 헤어라인을 쓰는 것은 별도 결정이다.
GENERIC_WHITES = {"rgba(255,255,255,.14)", "rgba(255,255,255,.10)",
                  "rgba(255,255,255,.45)"}

FAMILY_NUMBERS = sorted(
    ({v.replace(" ", "") for v in LINE_VALUES.values()}
     | {v.replace(" ", "") for v in INPUT_BORDER_VALUES.values()}
     | {v.replace(" ", "") for v in FOCUS_VALUES.values()}
     | {SURFACE_BORDER})
    - {w.replace(" ", "") for w in GENERIC_WHITES}
)


def _theme_blocks(tokens_text: str) -> dict[str, str]:
    blocks = {}
    for m in re.finditer(r'html\[data-theme="([a-z-]+)"\] \{', tokens_text):
        start = m.end()
        end = tokens_text.index("\n}", start)
        blocks[m.group(1)] = tokens_text[start:end]
    return blocks


class TestLineInputFocusTokens(unittest.TestCase):
    def test_the_token_file_defines_the_family_per_theme(self) -> None:
        text = TOKENS.read_text(encoding="utf-8")
        root = text[text.index(":root {"): text.index("\n}", text.index(":root {"))]
        self.assertIn("--line: #e3e3e9;", root)
        self.assertIn("--input-border-strong: #767e8a;", root)
        self.assertIn("--focus-ring: rgba(101, 87, 232, .24);", root)
        self.assertIn(f"--surface-border: {SURFACE_BORDER};", root)
        blocks = _theme_blocks(text)
        self.assertEqual(set(blocks),
                         {"light", "dark", "cinematic", "padiem-home", "padiem-glass"})
        for theme in blocks:
            self.assertIn(f"--line: {LINE_VALUES[theme]};", blocks[theme], theme)
            self.assertIn(f"--input-border-strong: {INPUT_BORDER_VALUES[theme]};",
                          blocks[theme], theme)
            self.assertIn(f"--focus-ring: {FOCUS_VALUES[theme]};", blocks[theme], theme)

    def test_no_other_sheet_defines_the_theme_level_family(self) -> None:
        """테마 수준 정의는 토큰 파일 안에서만 한다.

        padiem-themes.css·padiem-glass.css·padiem-dark-contrast.css가 갖고 있던
        정의를 옮겼으므로, 다른 시트의 html[data-theme=…] 블록이 이 토큰을
        정의하면 안 된다. 구성 요소가 스스로 좁게 덮는 값(예:
        claw-device-guidance의 어두운 표면용 --line)은 지역 결정으로 남고,
        html[data-theme=…] 전체를 덮는 정의만 금지한다.
        """
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS:
                continue
            text = sheet.read_text(encoding="utf-8")
            for m in re.finditer(r'html\[data-theme="([a-z-]+)"\] \{', text):
                block = text[m.end(): text.index("}", m.end())]
                for token in ("--line:", "--input-border-strong:", "--focus-ring:"):
                    if token in block:
                        offenders.append((sheet.name, m.group(1), token))
        self.assertEqual(offenders, [], offenders)

    def test_no_other_sheet_declares_the_family_numbers(self) -> None:
        """완료 기준: 패밀리 숫자는 토큰 파일(과 고정 styles.css)에만 있다.

        css_rules(#7186)로 선언 단위에서 읽는다. 검사 대상 선언은 실제로
        선·테두리·포커스를 그리는 border*/outline* 과 토큰 정의 자체다.
        같은 숫자라도 배경 그라디언트·글자색으로 쓰인 것은 별도 결정이므로
        대상 아니다.
        """
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS or sheet.name in FROZEN:
                continue
            for rule in parse_rules(sheet.read_text(encoding="utf-8")):
                for prop, value in rule.declarations.items():
                    p = prop.lower()
                    if not (p.startswith("border") or p.startswith("outline")
                            or p.startswith("--line") or p.startswith("--input")
                            or p.startswith("--focus") or p.startswith("--surface")):
                        continue
                    flat = value.replace(" ", "")
                    for number in FAMILY_NUMBERS:
                        if number in flat:
                            offenders.append((sheet.name, prop, value[:60]))
        self.assertEqual(offenders, [], offenders)

    def test_consumers_reference_the_tokens_without_fallbacks(self) -> None:
        """토큰이 항상 정의되므로 소비 규칙은 fallback 없이 쓴다."""
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet.name in FROZEN or sheet == TOKENS:
                continue
            text = sheet.read_text(encoding="utf-8")
            for token in ("--line,", "--focus-ring,", "--input-border-strong,"):
                self.assertNotIn(f"var({token}", text,
                                 f"{sheet.name}: var({token.rstrip(',')}, …) fallback")
        # 대표 소비 규칙들이 토큰을 가리키는지 확인한다(공유 카드 헤어라인).
        views = parse_rules((STATIC / "standalone-views.css").read_text(encoding="utf-8"))
        library = find_rules_with_selector(views, ".library-item")
        self.assertTrue(library)
        self.assertEqual(declaration(library[0], "border-color"), "var(--line)")
        mcp = (STATIC / "mcp-gateway-settings.css").read_text(encoding="utf-8")
        delegation = (STATIC / "pc-delegation-settings.css").read_text(encoding="utf-8")
        self.assertIn("var(--surface-border)", mcp)
        self.assertIn("var(--surface-border)", delegation)
        self.assertNotIn("var(--border,", mcp + delegation)
        legal = (STATIC / "legal-pages.css").read_text(encoding="utf-8")
        self.assertIn("--legal-line: var(--line);", legal)

    def test_the_standalone_legal_pages_load_the_token_sheet_first(self) -> None:
        for page in ("privacy.html", "terms.html"):
            html = (STATIC / page).read_text(encoding="utf-8")
            self.assertIn("padiem-tokens.css", html, page)
            self.assertLess(html.index("padiem-tokens.css"),
                            html.index("legal-pages.css"), page)

    def test_the_app_loads_tokens_before_the_theme_sheet(self) -> None:
        """토큰 파일이 테마 시트보다 먼저여야 테마 정의 소유권이 여기 성립한다."""
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("padiem-tokens.css"),
                        html.index("padiem-themes.css"))
        self.assertLess(html.index("padiem-tokens.css"),
                        html.index("padiem-dark-contrast.css"))


if __name__ == "__main__":
    unittest.main()
