"""#7187 R3 3차 — 카드 테두리와 accent 계열 색도 토큰 파일 한 곳에.

1차(#7256)가 주요 버튼 남색을, 2차(#7263)가 선·입력칸·포커스를 모았다면
3차는 같은 방식을 카드 테두리(``--card-border``)와 accent 계열
(``--accent`` / ``--accent-contrast`` / ``--accent-soft`` /
``--accent-strong``)에 적용한다:

* 원래 padiem-themes.css의 네 테마 블록, padiem-glass.css,
  padiem-dark-contrast.css가 나눠 정의했다. 값은 측정값 그대로 옮기고
  정의는 padiem-tokens.css 한 곳에만 둔다.
* dark의 실제 값은 padiem-dark-contrast.css가 덮어쓰던 것(#9bcdf0·#d1ebfb·
  #455b70)이다 — 2차의 --line(#405365)과 같은 판정법.
* styles.css의 :root도 --accent/--accent-soft/--accent-strong을 정의하지만
  바이트 고정(참조 미러)이라 그대로 두고, 토큰 파일이 같은 값을 다시
  선언해 유일한 수정 지점 역할을 한다. --accent-contrast는 styles.css에
  없어서 토큰 파일이 유일한 정의다.
* 토큰이 항상 정의되므로 소비 규칙은 fallback 없이 쓴다. 기존
  ``var(--accent…, 숫자)`` fallback 96곳·26시트와 ``var(--card-border, …)``
  1곳은 화면 결과를 바꾸지 않고 제거했다(fallback은 정의가 없을 때만
  쓰이므로). 유일한 예외적 변화는 테마 적용 전 한 프레임의 util-menu
  카드 테두리인데, fallback 값 rgba(255,255,255,.42)는 padiem-glass 값이
  기본 light 체계(:root)와 섞여 있던 것으로, 이제 :root 기본값과 일치한다.

제외한 지역 결정(이 시험에 근거를 기록한다):

* padiem-foundation.css :root — 채팅 5테마 체계 밖의 별개 화면(프로젝트
  커서 페이지)이 자체로 다크 기본값을 갖는 구성 요소 지역 결정. 채팅
  페이지 어디에도 로드되지 않는다(아래 시험이 확인).
* voice·admin 계열 시트 — 조사 결과 --accent*/--card-border 정의가 없다.
  지역 팔레트가 다른 이름의 변수를 쓰는 것이므로 이번 패밀리와 무관하다.
* --accent-contrast의 어두운 숫자(#131417·#04070d·#0b0f14·#17202a)는
  일반 글자색으로도 쓰이는 값이라 숫자 스캔 대상에서 뺐다(아래 시험 주석).
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
ACCENT_VALUES = {
    "light": "#6557e8",
    "dark": "#9bcdf0",  # padiem-dark-contrast.css가 덮어쓰던 실제 값
    "cinematic": "#88c9ff",
    "padiem-home": "#3a7bd5",
    "padiem-glass": "#79bce7",
}
ACCENT_CONTRAST_VALUES = {
    "light": "#ffffff",
    "dark": "#131417",
    "cinematic": "#04070d",
    "padiem-home": "#0b0f14",
    "padiem-glass": "#17202a",
}
ACCENT_SOFT_VALUES = {
    "light": "#efedff",
    "dark": "rgba(159,192,221,.08)",
    "cinematic": "rgba(136,201,255,.10)",
    "padiem-home": "rgba(58,123,213,.10)",
    "padiem-glass": "rgba(121, 188, 231, .16)",
}
ACCENT_STRONG_VALUES = {
    "light": "#5546d6",
    "dark": "#d1ebfb",  # padiem-dark-contrast.css가 덮어쓰던 실제 값
    "cinematic": "#d7ebfa",
    "padiem-home": "#2a5fa8",
    "padiem-glass": "#2f6f99",
}
CARD_BORDER_VALUES = {
    "light": "#e3e3e9",
    "dark": "#455b70",  # padiem-dark-contrast.css가 덮어쓰던 실제 값
    "cinematic": "rgba(136,201,255,.16)",
    "padiem-home": "rgba(26,34,48,.10)",
    "padiem-glass": "rgba(255, 255, 255, .42)",
}

#: 숫자 스캔 대상에서 뺀 값과 이유.
#: - #ffffff / #e3e3e9: 너무 흔한 공용 값(#e3e3e9는 2차 --line이 이미 소유).
#: - #131417·#04070d·#0b0f14·#17202a: --accent-contrast의 어두운 글자색이지만
#:   같은 숫자가 일반 글자색으로도 쓰인다 — 별도 결정.
#: - rgba(255,255,255,.09) / rgba(26,34,48,.10): 다크·라이트 공용 미세
#:   헤어라인. 카드 테두리 토큰과 숫자만 같고 의미가 다른 구성 요소 지역
#:   값(padiem-rich 본문 표, shared-tooltip, 시네마틱 작업대, 홈 컴포저
#:   그림자)이라 2차 GENERIC_WHITES와 같은 취지로 뺀다.
#: - rgba(255,255,255,.42): 유리 카드 테두리 값이지만 같은 반투명 백색이
#:   그라디언트 중간 지점 등으로 너무 흔히 쓰인다(2차 GENERIC_WHITES 취지).
#:   유리 테마 정의 소유는 위의 테마 블록 검사가 지킨다.
SCAN_EXCLUDED = {"#ffffff", "#e3e3e9", "#131417", "#04070d", "#0b0f14", "#17202a",
                 "rgba(255,255,255,.09)", "rgba(26,34,48,.10)",
                 "rgba(255,255,255,.42)"}

#: 시트별 지역 팔레트 허용(대표의 voice·admin 제외 결정). admin-models의
#: 버튼 hover 배경은 유리 테마 인접 색을 테마와 무관하게 고정으로 쓰는
#: admin 지역 팔레트라 이번 패밀리 대상이 아니다.
LOCAL_PALETTE_ALLOWANCE = {
    ("admin-models.css", "rgba(121,188,231,.16)"),
}

#: 스캔하는 패밀리 숫자(공백 제거 형태). --blue 같은 다른 토큰 정의가 같은
#: 숫자를 재사용하는 것(--blue: #88c9ff)은 정의가 아니라 별도 토큰이므로
#: 스캔에서 사용 속성만 본다(아래 시험).
FAMILY_NUMBERS = sorted(
    {v.replace(" ", "") for values in (
        ACCENT_VALUES, ACCENT_SOFT_VALUES, ACCENT_STRONG_VALUES,
        CARD_BORDER_VALUES,
    ) for v in values.values()}
    - SCAN_EXCLUDED
)


def _theme_blocks(tokens_text: str) -> dict[str, str]:
    blocks = {}
    for m in re.finditer(r'html\[data-theme="([a-z-]+)"\] \{', tokens_text):
        start = m.end()
        end = tokens_text.index("\n}", start)
        blocks[m.group(1)] = tokens_text[start:end]
    return blocks


class TestCardAccentTokens(unittest.TestCase):
    def test_the_token_file_defines_the_family_per_theme(self) -> None:
        text = TOKENS.read_text(encoding="utf-8")
        root = text[text.index(":root {"): text.index("\n}", text.index(":root {"))]
        self.assertIn("--accent: #6557e8;", root)
        self.assertIn("--accent-contrast: #ffffff;", root)
        self.assertIn("--accent-soft: #efedff;", root)
        self.assertIn("--accent-strong: #5546d6;", root)
        self.assertIn("--card-border: #e3e3e9;", root)
        blocks = _theme_blocks(text)
        self.assertEqual(set(blocks),
                         {"light", "dark", "cinematic", "padiem-home", "padiem-glass"})
        for theme in blocks:
            self.assertIn(f"--accent: {ACCENT_VALUES[theme]};", blocks[theme], theme)
            self.assertIn(f"--accent-contrast: {ACCENT_CONTRAST_VALUES[theme]};",
                          blocks[theme], theme)
            self.assertIn(f"--accent-soft: {ACCENT_SOFT_VALUES[theme]};",
                          blocks[theme], theme)
            self.assertIn(f"--accent-strong: {ACCENT_STRONG_VALUES[theme]};",
                          blocks[theme], theme)
            self.assertIn(f"--card-border: {CARD_BORDER_VALUES[theme]};",
                          blocks[theme], theme)

    def test_no_other_sheet_defines_the_theme_level_family(self) -> None:
        """테마 수준 정의는 토큰 파일 안에서만 한다.

        padiem-themes.css(네 테마 블록)·padiem-glass.css·
        padiem-dark-contrast.css가 갖고 있던 정의를 옮겼으므로, 다른 시트의
        html[data-theme=…] 블록이 이 토큰을 정의하면 안 된다.
        padiem-foundation.css의 :root 정의는 data-theme 블록이 아니므로
        이 검사에 걸리지 않는다 — 별개 화면의 지역 결정(모듈 독스트링 참고).
        """
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS:
                continue
            text = sheet.read_text(encoding="utf-8")
            for m in re.finditer(r'html\[data-theme="([a-z-]+)"\] \{', text):
                block = text[m.end(): text.index("}", m.end())]
                for token in ("--accent:", "--accent-contrast:", "--accent-soft:",
                              "--accent-strong:", "--card-border:"):
                    if token in block:
                        offenders.append((sheet.name, m.group(1), token))
        self.assertEqual(offenders, [], offenders)

    def test_no_other_sheet_declares_the_family_numbers(self) -> None:
        """완료 기준: 패밀리 숫자는 토큰 파일(과 고정 styles.css)에만 있다.

        css_rules(#7186)로 선언 단위에서 읽는다. 사용 속성(color·background·
        border*·outline*·box-shadow·fill·stroke)만 보고, 사용자 정의 속성
        정의(--blue: #88c9ff 처럼 다른 토큰이 같은 숫자를 재사용하는 것)는
        검사 대상에서 뺀다 — 그 정의 자체가 별도 토큰의 값이기 때문이다.
        """
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS or sheet.name in FROZEN:
                continue
            for rule in parse_rules(sheet.read_text(encoding="utf-8")):
                for prop, value in rule.declarations.items():
                    p = prop.lower()
                    if p.startswith("--"):
                        continue
                    if not (p == "color" or p.startswith("background")
                            or p.startswith("border") or p.startswith("outline")
                            or p.startswith("box-shadow") or p in ("fill", "stroke")):
                        continue
                    flat = value.replace(" ", "")
                    for number in FAMILY_NUMBERS:
                        if number in flat and (sheet.name, number) not in LOCAL_PALETTE_ALLOWANCE:
                            offenders.append((sheet.name, prop, value[:60]))
        self.assertEqual(offenders, [], offenders)

    def test_consumers_reference_the_tokens_without_fallbacks(self) -> None:
        """토큰이 항상 정의되므로 소비 규칙은 fallback 없이 쓴다."""
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet.name in FROZEN or sheet == TOKENS:
                continue
            text = sheet.read_text(encoding="utf-8")
            for token in ("--accent,", "--accent-contrast,", "--accent-soft,",
                          "--accent-strong,", "--card-border,"):
                self.assertNotIn(f"var({token}", text,
                                 f"{sheet.name}: var({token.rstrip(',')}, …) fallback")
        # 대표 소비 규칙들이 토큰을 가리키는지 확인한다.
        calendar = (STATIC / "calendar.css").read_text(encoding="utf-8")
        self.assertIn("var(--accent-strong)", calendar)
        self.assertNotIn("#2f6f99", calendar)
        workspace = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")
        self.assertIn("var(--accent-contrast)", workspace)
        util = (STATIC / "util-menu.css").read_text(encoding="utf-8")
        self.assertIn("var(--card-border)", util)
        themes = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")
        self.assertIn("border-color: var(--card-border);", themes)

    def test_the_literal_accent_copies_now_reference_the_token(self) -> None:
        """패밀리 숫자를 글자로 쓰던 대표 규칙이 토큰을 가리킨다.

        답변 액션 버튼(밝은 남색 글자·포커스·눌림 테두리)과 유리 테마
        세로화면 포커스선, 홈 눈금 텍스트는 --accent 값을 글자로 복사해
        두고 있었다. 토큰 참조로 바꾸면 밝은 테마에서는 같은 값이고
        다른 테마에서는 그 테마의 accent를 따라간다(토큰화의 목적).
        """
        answer = (STATIC / "answer-actions.css").read_text(encoding="utf-8")
        self.assertIn("outline: 2px solid var(--accent);", answer)
        self.assertIn("border-color: var(--accent);", answer)
        self.assertIn("color: var(--accent);", answer)
        self.assertNotIn("#6557e8", answer)
        portrait = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")
        self.assertIn("outline: 2px solid var(--accent) !important;", portrait)
        capability = (STATIC / "capability-nav.css").read_text(encoding="utf-8")
        self.assertIn("background: var(--accent-soft);", capability)
        themes = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")
        self.assertIn(".eyebrow { color: var(--accent);", themes)
        self.assertIn(".eyebrow::before { background: var(--accent);", themes)

    def test_the_foundation_surface_keeps_its_own_palette(self) -> None:
        """제외 근거: padiem-foundation.css는 채팅 5테마 체계 밖의 별개 화면.

        프로젝트 커서 페이지가 자체로 다크 기본값을 갖는 구성 요소 지역
        결정이고, 채팅 페이지 어디에도 로드되지 않는다(아래에서 확인).
        토큰 파일이 이 시트를 건드리지 않았으므로 그 화면은 변화가 없다.
        """
        foundation = (STATIC / "padiem-foundation.css").read_text(encoding="utf-8")
        self.assertIn("--accent: #88c9ff;", foundation)
        self.assertIn("--accent-soft: rgba(136, 201, 255, .055);", foundation)
        self.assertIn("--accent-strong: #d7ebfa;", foundation)
        for page in ("index.html", "privacy.html", "terms.html",
                     "help.html", "install.html"):
            html = (STATIC / page).read_text(encoding="utf-8")
            self.assertNotIn("padiem-foundation.css", html, page)

    def test_the_local_palette_sheets_define_no_accent_family(self) -> None:
        """제외 근거: voice·admin 계열 지역 팔레트는 이번 패밀리와 무관하다.

        조사 결과 그 시트들은 --accent*/--card-border를 정의하지 않는다(다른
        이름의 지역 변수를 쓴다). 정의가 없으므로 옮길 것도 남길 것도 없다.
        """
        for name in ("voice-composer.css", "voice-session.css", "admin.css",
                     "admin-models.css"):
            sheet = STATIC / name
            if not sheet.exists():
                continue
            text = sheet.read_text(encoding="utf-8")
            for token in ("--accent:", "--accent-contrast:", "--accent-soft:",
                          "--accent-strong:", "--card-border:"):
                self.assertNotIn(token, text, f"{name}: {token}")


if __name__ == "__main__":
    unittest.main()
