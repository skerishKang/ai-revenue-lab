"""#7975 UI contract: the new badge module stays small, token-only and honest.

No browser is needed here: browser screenshots for the three states live in
padiem-reports/2026-11-18/7975-pc-command-ready/. This pins the source-level
contract that CI can always check.
"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
MODULE = STATIC / "pc-command-ready.js"
CARD_CSS = STATIC / "pc-pairing-card.css"
INDEX = STATIC / "index.html"


def test_new_module_is_its_own_small_file():
    source = MODULE.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 1000
    assert '"/api/pc/pairings"' in source
    assert "command_ready" in source
    assert "innerHTML" not in source
    assert "eval(" not in source


def test_badge_copy_is_plain_korean_and_offers_the_remedy():
    source = MODULE.read_text(encoding="utf-8")
    assert "연결됨 · 명령 준비 안 됨" in source
    assert "Windows 로 로그인돼 있는지 확인하고" in source
    assert "PC 도우미를 다시 설치해 주세요" in source
    # A link with no evidence is never given a warning.
    assert '!== "not_ready"' in source


def test_existing_theme_styles_are_reused_without_a_new_sheet():
    source = MODULE.read_text(encoding="utf-8")
    assert not (STATIC / "pc-command-ready.css").exists()
    assert 'element("p", "pc-pairing-help"' in source
    assert 'dataset.state !== "offline"' in source
    css = CARD_CSS.read_text(encoding="utf-8")
    assert ".pc-pairing-help {" in css
    assert '[data-state="offline"]' in css


def test_index_wires_module_after_the_pairing_card():
    html = INDEX.read_text(encoding="utf-8")
    card = html.index('./pc-pairing-card.js')
    module = html.index('./pc-command-ready.js')
    assert module > card
