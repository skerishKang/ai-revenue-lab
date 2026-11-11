"""#7187 R3 5차 — 테마 팔레트 소유권을 padiem-tokens.css 한 곳으로.

1차(#7256) 주요 버튼, 2차(#7263) 선·입력칸·포커스, 3차(#7277) 카드 테두리·accent,
4차(#7494) PC 연결 클러스터에 이어, 5차는 테마 팔레트 전체를 옮긴다:

* ``padiem-themes.css``의 네 테마 블록(light/dark/cinematic/padiem-home),
  ``padiem-glass.css``의 glass 블록, ``padiem-dark-contrast.css``의 dark 덮어쓰기가
  나눠 정의하던 표면·의미 색·그림자·반경·타이포 값을 ``padiem-tokens.css``가
  소유한다. 값은 측정값 그대로이고, dark는 실제로 적용되던 dark-contrast 값을 쓴다.
* 소비 앱도 토큰 시트를 로드한다: Chat ``index.html``(기존), React 클론
  ``operational.css``, council 앱 ``index.html``. 토큰 시트가 styles.css 뒤,
  테마 시트 앞에 오는 순서는 index.html과 같다.
* 예외: glass의 ``--card-bg``는 ``padiem-glass-portrait.css``의 실제 값(.92)과
  좁은 화면 미디어 규칙이 이 파일보다 뒤에 로드되는 순서 때문에 glass.css가
  계속 소유한다. 글래스 아트/변형 변수(``--glass-*``·``--glass-shell-*``)는
  조건부 화면 결정이라 각 시트에 남는다. ``color-scheme``·배경색·이미지 슬롯도
  테마 시트에 남는다(토큰 아님).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

TOKENS = STATIC / "padiem-tokens.css"
THEMES = STATIC / "padiem-themes.css"
GLASS = STATIC / "padiem-glass.css"
CONTRAST = STATIC / "padiem-dark-contrast.css"

#: 5차 이전 소스(origin/main)에서 읽은 값. dark는 dark-contrast가 실제로
#: 덮어쓰던 값이다. 각 테마 시트에서 옮겨 온 그대로다.
THEME_VALUES = {'cinematic': {'--assistant-surface-bg': 'rgba(255,255,255,.045)',
               '--bg': '#04070d',
               '--blue': '#88c9ff',
               '--card-bg': 'rgba(8,12,19,.52)',
               '--composer-bg': 'rgba(10,14,22,.68)',
               '--composer-border': 'rgba(136,201,255,.22)',
               '--danger': '#ff9d9d',
               '--danger-border': 'rgba(220, 62, 62, 0.16)',
               '--danger-surface': 'rgba(220, 62, 62, 0.07)',
               '--film-blue-glow': 'rgba(108,190,255,.16)',
               '--film-edge': 'rgba(136,201,255,.18)',
               '--film-gold-glow': 'rgba(239,201,132,.10)',
               '--film-grain': '.22',
               '--film-vignette': 'inset 0 0 280px 110px rgba(0,0,0,.72)',
               '--gold': '#efc984',
               '--gold-soft': 'rgba(239,201,132,.14)',
               '--muted': 'rgba(255,255,255,.68)',
               '--page-bg': '#04070d',
               '--panel': 'rgba(10,14,22,.72)',
               '--shadow': '0 24px 80px rgba(0,0,0,.42)',
               '--sidebar': 'rgba(6,9,15,.88)',
               '--success': '#8be9a8',
               '--success-border': 'rgba(34, 158, 94, 0.18)',
               '--success-surface': 'rgba(34, 158, 94, 0.08)',
               '--text': '#f7f8fa',
               '--topbar-bg': 'linear-gradient(180deg, rgba(7,11,19,.72), rgba(6,9,15,.14))',
               '--user-bubble-bg': 'rgba(255,255,255,.085)',
               '--user-bubble-text': 'rgba(255,255,255,.92)'},
 'dark': {'--assistant-surface-bg': '#1c2835',
          '--bg': '#10151c',
          '--blue': '#9fc0dd',
          '--card-bg': '#202d3a',
          '--composer-bg': '#242e3a',
          '--composer-border': '#536778',
          '--danger': '#ff9d9d',
          '--danger-border': 'rgba(220, 62, 62, 0.16)',
          '--danger-surface': 'rgba(220, 62, 62, 0.07)',
          '--gold': '#c9b28a',
          '--gold-soft': 'rgba(201,178,138,.07)',
          '--muted': '#b4c2d0',
          '--page-bg': '#10151c',
          '--panel': '#1a232d',
          '--shadow': '0 10px 28px rgba(0,0,0,.28)',
          '--sidebar': '#0e141b',
          '--success': '#8be9a8',
          '--success-border': 'rgba(34, 158, 94, 0.18)',
          '--success-surface': 'rgba(34, 158, 94, 0.08)',
          '--text': '#edf4fa',
          '--topbar-bg': '#121b25',
          '--user-bubble-bg': '#263545',
          '--user-bubble-text': '#f2f7fc',
          '--utility-edge': 'rgba(255,255,255,.12)',
          '--utility-surface': '#1a1b1f'},
 'light': {'--assistant-surface-bg': '#ffffff',
           '--assistant-surface-border': '#e3e3e9',
           '--bg': '#f8f8fb',
           '--blue': '#6557e8',
           '--card-bg': '#ffffff',
           '--card-shadow': '0 3px 10px rgba(33,33,49,.04)',
           '--composer-bg': '#ffffff',
           '--composer-border': '#e3e3e9',
           '--composer-shadow': '0 14px 36px rgba(30,28,54,.08)',
           '--danger': '#b3261e',
           '--danger-border': 'rgba(220, 62, 62, 0.16)',
           '--danger-surface': 'rgba(220, 62, 62, 0.07)',
           '--font-body': 'Pretendard, "Noto Sans KR", Inter, ui-sans-serif, system-ui, '
                          '-apple-system, sans-serif',
           '--font-display': 'Pretendard, "Noto Sans KR", ui-sans-serif',
           '--font-label': 'Inter, Pretendard, system-ui, sans-serif',
           '--glass': 'rgba(255,255,255,.72)',
           '--gold': '#b8923a',
           '--gold-soft': 'rgba(184,146,58,.10)',
           '--input-text': '#19191d',
           '--muted': '#6f7079',
           '--page-bg': '#f8f8fb',
           '--panel': '#ffffff',
           '--placeholder': '#9b9ca5',
           '--radius-md': '16px',
           '--shadow': '0 14px 36px rgba(30,28,54,.08)',
           '--sidebar': '#f1f1f5',
           '--sidebar-text': '#19191d',
           '--success': '#1a6b3a',
           '--success-border': 'rgba(34, 158, 94, 0.18)',
           '--success-surface': 'rgba(34, 158, 94, 0.08)',
           '--text': '#19191d',
           '--topbar-bg': 'rgba(248,248,251,.86)',
           '--user-bubble-bg': '#6557e8',
           '--user-bubble-border': 'transparent',
           '--user-bubble-text': '#ffffff'},
 'padiem-glass': {'--assistant-surface-bg': 'rgba(244, 247, 249, .36)',
                  '--assistant-surface-border': 'rgba(255, 255, 255, .40)',
                  '--bg': '#aeb6bf',
                  '--blue': '#79bce7',
                  '--card-shadow': '0 18px 48px rgba(28, 38, 49, .14), inset 0 1px 0 rgba(255, '
                                   '255, 255, .58)',
                  '--composer-bg': 'rgba(244, 247, 249, .58)',
                  '--composer-border': 'rgba(255, 255, 255, .54)',
                  '--composer-shadow': '0 22px 58px rgba(26, 35, 44, .18), inset 0 1px 0 '
                                       'rgba(255, 255, 255, .66)',
                  '--danger': '#7f1d1d',
                  '--danger-border': 'rgba(127, 29, 29, .28)',
                  '--danger-surface': 'rgba(253, 247, 247, .92)',
                  '--glass': 'rgba(244, 247, 249, .42)',
                  '--gold': '#c7a76b',
                  '--gold-soft': 'rgba(199, 167, 107, .14)',
                  '--input-text': '#17202a',
                  '--muted': '#53606c',
                  '--page-bg': '#aeb6bf',
                  '--panel': 'rgba(235, 239, 242, .46)',
                  '--placeholder': 'rgba(35, 45, 55, .48)',
                  '--shadow': '0 20px 60px rgba(24, 33, 42, .16)',
                  '--sidebar': 'rgba(42, 50, 59, .46)',
                  '--sidebar-text': '#f7f9fb',
                  '--success': '#14532d',
                  '--success-border': 'rgba(20, 83, 45, .28)',
                  '--success-surface': 'rgba(247, 251, 249, .92)',
                  '--text': '#17202a',
                  '--topbar-bg': 'rgba(47, 56, 65, .36)',
                  '--user-bubble-bg': 'rgba(33, 45, 57, .76)',
                  '--user-bubble-text': '#ffffff'},
 'padiem-home': {'--assistant-surface-bg': 'rgba(255,255,255,.62)',
                 '--bg': '#e6e9ee',
                 '--blue': '#5aa0e6',
                 '--card-bg': 'rgba(255,255,255,.68)',
                 '--composer-bg': 'rgba(255,255,255,.82)',
                 '--composer-border': 'rgba(26,34,48,.13)',
                 '--danger': '#b3261e',
                 '--danger-border': 'rgba(220, 62, 62, 0.16)',
                 '--danger-surface': 'rgba(220, 62, 62, 0.07)',
                 '--gold': '#c9a85c',
                 '--gold-soft': 'rgba(201,168,92,.12)',
                 '--muted': '#5a6578',
                 '--page-bg': '#e6e9ee',
                 '--panel': 'rgba(255,255,255,.72)',
                 '--shadow': '0 18px 50px rgba(26,34,48,.10)',
                 '--sidebar': 'rgba(255,255,255,.62)',
                 '--success': '#14532d',
                 '--success-border': 'rgba(34, 158, 94, 0.18)',
                 '--success-surface': 'rgba(34, 158, 94, 0.08)',
                 '--text': '#1a2230',
                 '--topbar-bg': 'rgba(255,255,255,.55)',
                 '--user-bubble-bg': '#1a2230',
                 '--user-bubble-text': '#ffffff'}}

MOVED = sorted({name for values in THEME_VALUES.values() for name in values})


def _block(text: str, theme: str) -> str:
    match = re.search(r'html\[data-theme="%s"\] \{' % re.escape(theme), text)
    assert match is not None, theme
    return text[match.end(): text.index("\n}", match.end())]


def _custom_property_declarations(block: str) -> list[str]:
    return re.findall(r"(--[\w-]+)\s*:", block)


class TestThemePaletteTokens(unittest.TestCase):
    def test_the_token_file_owns_every_theme_value(self) -> None:
        text = TOKENS.read_text(encoding="utf-8")
        for theme, values in THEME_VALUES.items():
            block = _block(text, theme)
            for name, value in values.items():
                self.assertIn(f"{name}: {value};", block, (theme, name))

    def test_the_theme_sheets_keep_no_palette_definitions(self) -> None:
        for path in (THEMES, GLASS):
            text = path.read_text(encoding="utf-8")
            for theme in THEME_VALUES:
                try:
                    block = _block(text, theme)
                except AssertionError:
                    continue
                declarations = _custom_property_declarations(block)
                if path == GLASS:
                    # glass.css keeps the image slot and the documented --card-bg
                    # exception; the rest moved to the token sheet.
                    self.assertEqual(
                        declarations,
                        ["--padiem-glass-background-image", "--card-bg"], theme)
                else:
                    self.assertEqual(declarations, [], (path.name, theme))
                self.assertIn("color-scheme:", block, (path.name, theme))

        contrast = CONTRAST.read_text(encoding="utf-8")
        self.assertNotIn('html[data-theme="dark"] {', contrast)
        self.assertIn('html[data-theme="dark"] body', contrast)

    def test_no_other_sheet_owns_the_theme_palette(self) -> None:
        """베어 테마 블록에서 같은 값을 다시 정의하지 않는다.

        glass portrait의 --card-bg는 문서화된 예외다(값 .92가 실제 적용값).
        """
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS:
                continue
            text = sheet.read_text(encoding="utf-8")
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            for match in re.finditer(r'html\[data-theme="([a-z-]+)"\] \{', text):
                block = text[match.end(): text.index("}", match.end())]
                for name in re.findall(r"(--[\w-]+)\s*:", block):
                    if name not in MOVED:
                        continue
                    if sheet.name == "padiem-glass-portrait.css" and name == "--card-bg":
                        continue
                    if sheet.name == "padiem-glass.css" and name == "--card-bg":
                        continue
                    offenders.append((sheet.name, match.group(1), name))
        self.assertEqual(offenders, [], offenders)

    def test_the_glass_card_exception_is_pinned(self) -> None:
        glass = GLASS.read_text(encoding="utf-8")
        portrait = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")
        tokens = TOKENS.read_text(encoding="utf-8")
        self.assertIn("--card-bg: rgba(239, 243, 246, .48);", glass)
        self.assertIn("--card-bg: rgba(239, 243, 246, .92);", portrait)
        self.assertNotIn("--card-bg:", _block(tokens, "padiem-glass"))
        # The narrow-window rule still outranks the base value it follows.
        self.assertIn("@media (max-width: 920px)", portrait)

    def test_the_theme_sheets_keep_their_component_rules(self) -> None:
        themes = THEMES.read_text(encoding="utf-8")
        glass = GLASS.read_text(encoding="utf-8")
        for theme in ("light", "dark", "cinematic", "padiem-home"):
            self.assertIn(f'html[data-theme="{theme}"] .sidebar', themes, theme)
        self.assertIn('html[data-theme="dark"] .composer-note', themes)
        self.assertIn('html[data-theme="cinematic"] .composer-note', themes)
        self.assertIn('html[data-theme="padiem-glass"] .composer', glass)
        self.assertIn("background-color: #aeb6bf", glass)
        self.assertIn("--padiem-glass-background-image: none", glass)

    def test_the_consuming_apps_load_the_token_sheet_first(self) -> None:
        chat = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(chat.index("padiem-tokens.css"),
                        chat.index("padiem-themes.css"))
        self.assertLess(chat.index("padiem-tokens.css"),
                        chat.index("padiem-dark-contrast.css"))

        work = ROOT.parents[1]
        react = (work / "apps" / "padiem-chat-react" / "src" / "styles"
                 / "operational.css").read_text(encoding="utf-8")
        self.assertLess(react.index("static/styles.css"),
                        react.index("static/padiem-tokens.css"))
        self.assertLess(react.index("static/padiem-tokens.css"),
                        react.index("static/padiem-themes.css"))
        self.assertLess(react.index("static/padiem-tokens.css"),
                        react.index("static/padiem-dark-contrast.css"))

        council = (work / "apps" / "padiem-council-apps" / "static"
                   / "index.html").read_text(encoding="utf-8")
        self.assertLess(council.index("/padiem-tokens.css"),
                        council.index("/padiem-themes.css"))


if __name__ == "__main__":
    unittest.main()
