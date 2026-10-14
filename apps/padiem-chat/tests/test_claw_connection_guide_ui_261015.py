"""Claw's compact connection guide must not become connector authority or alter shared Chat layout."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC / "claw-connection-guide.js").read_text(encoding="utf-8")
STYLE = (STATIC / "claw-connection-guide.css").read_text(encoding="utf-8")


def test_three_existing_switches_share_one_compact_native_dialog():
    assert HTML.count('id="clawConnectionGuide"') == 1
    assert HTML.count('aria-controls="clawConnectionGuide"') == 3
    assert HTML.count('aria-haspopup="dialog"') >= 3
    assert HTML.index('src="./claw-connection-chips.js"') < HTML.index('src="./claw-connection-guide.js"')
    assert HTML.index('href="./claw-connection-guide.css"') < HTML.index('href="./claw-focus-layout.css"')


def test_guide_keeps_canonical_state_and_no_fake_install_or_oauth():
    assert 'button.dataset.connectionState' in SCRIPT
    assert 'state === "unknown"' in SCRIPT
    assert "event.stopImmediatePropagation()" in SCRIPT
    assert 'document.getElementById(cardIds[id])?.click()' in SCRIPT
    assert 'source?.focus(' in SCRIPT
    assert "dialog.showModal()" in SCRIPT
    assert 'localStorage' not in SCRIPT
    assert 'fetch(' not in SCRIPT
    assert 'dataset.connectionState =' not in SCRIPT
    assert 'https://' not in SCRIPT


def test_installation_defaults_are_shown_without_second_login_step():
    assert "설치가 끝나면 자동으로 실행되어 CLAW와 연결됩니다." in SCRIPT
    assert "별도 로그인이나 '프로그램 켜기' 단계는 필요하지 않습니다." in SCRIPT
    assert "설치 후 자동 실행·연결됩니다." in SCRIPT


def test_drive_disconnect_is_explicit_not_a_fake_pause():
    assert 'intent === "disconnect-drive"' in SCRIPT
    assert 'button.click()' in SCRIPT
    assert '잠시 사용 중지하는 기능은 별도로 제공될 예정입니다.' in SCRIPT
    assert "연결 해제" in SCRIPT


def test_guide_styles_do_not_touch_shared_chat_or_card_geometry():
    assert ".claw-connection-guide" in STYLE
    assert "max-width: 390px" in STYLE
    assert "max-height: min(520px" in STYLE
    assert ".composer" not in STYLE
    assert ".starter" not in STYLE
    assert ".claw-home-card" not in STYLE
