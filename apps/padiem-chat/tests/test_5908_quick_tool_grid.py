"""#5908 (갱신 #7173 / #7460) — 유틸 첫 화면의 여섯 카드.

- 카드마다 붙어 있던 "열기 / 이력 열기 / Claw에서 작성 / Claw에서 진행" 버튼을 없애고,
  **카드 전체**가 유틸 앱 안의 그 도구 화면을 연다.
- #7460: 여섯 도구 정의는 단일 등록부(static/util-manifest.js)에 있고,
  util-app.js가 그 등록부에서 카드와 칩을 그린다. 상단 #appSwitch는 제거되었다.
"""
from __future__ import annotations

from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
UTIL_MANIFEST_JS = (STATIC / "util-manifest.js").read_text(encoding="utf-8")
UTIL_APP_JS = (STATIC / "util-app.js").read_text(encoding="utf-8")
UTIL_APP_CSS = (STATIC / "util-app.css").read_text(encoding="utf-8")

TOOLS = (
    ("speech", "축사·인사말", "행사 축사·인사말 초안 생성·저장"),
    ("sns", "SNS 홍보", "블로그·페이스북·인스타그램 초안"),
    ("meeting", "회의정리·활동집", "회의 요약·책/활동집 누적 생성"),
    ("pdfmd", "PDF → Markdown", "PDF·ZIP을 Markdown으로 변환·비교·다운로드"),
    ("quote", "견적서 초안", "요청을 붙이면 견적서·발주서·답장 초안"),
    ("excel", "Excel 열기/검토", "XLSX 원본을 이 화면에서 열어 검토·작업"),
)


# ── markup boundary ────────────────────────────────────────────────────────


def test_the_six_cards_live_in_the_util_manifest_and_app_module() -> None:
    for tool_id, title, desc in TOOLS:
        assert f'id: "{tool_id}"' in UTIL_MANIFEST_JS, tool_id
        assert f'"{title}"' in UTIL_MANIFEST_JS, title
        assert desc in UTIL_MANIFEST_JS, desc
    assert "window.PadiemUtilManifest" in UTIL_APP_JS
    assert 'id="utilToolGrid"' not in INDEX
    assert "data-quick-util" not in INDEX


def test_cards_are_whole_clickable_buttons_without_secondary_actions() -> None:
    assert 'element("button", "util-card")' in UTIL_APP_JS
    assert 'setAttribute("data-util-route"' in UTIL_APP_JS
    for gone in ("util-tool-open", "이력 열기", "Claw에서 작성", "Claw에서 진행"):
        assert gone not in UTIL_APP_JS, gone
        assert gone not in UTIL_MANIFEST_JS, gone
    assert "clawQuoteCard" not in UTIL_APP_JS
    assert "clawNavButton.click" not in UTIL_APP_JS


def test_card_copy_does_not_claim_a_claw_flow_for_quote_or_excel() -> None:
    quote = UTIL_MANIFEST_JS[UTIL_MANIFEST_JS.index('id: "quote"'):UTIL_MANIFEST_JS.index('id: "excel"')]
    excel = UTIL_MANIFEST_JS[UTIL_MANIFEST_JS.index('id: "excel"'):UTIL_MANIFEST_JS.index("const TOOL_BY_ID")]
    assert "Claw" not in quote
    assert "Claw" not in excel
    assert "견적서·발주서·답장 초안" in quote
    assert "이 화면에서 열어" in excel


# ── CSS contract ───────────────────────────────────────────────────────────


def test_card_css_keeps_the_shared_tokens_hover_and_phone_floor() -> None:
    rules = parse_rules(UTIL_APP_CSS)
    cards = find_rules_with_selector(rules, ".util-card")
    assert cards
    assert any((declaration(rule, "border") or "").startswith("1px solid var(--line")
               for rule in cards)
    assert any(declaration(rule, "cursor") == "pointer" for rule in cards)
    assert ".util-card-grid" in UTIL_APP_CSS
    focus = find_rules_with_selector(rules, ".util-card:focus-visible")
    assert focus and declaration(focus[0], "outline") == "3px solid var(--primary-focus)"
    assert "@media (max-width: 720px)" in UTIL_APP_CSS
    assert ".util-tool-chip" in UTIL_APP_CSS
