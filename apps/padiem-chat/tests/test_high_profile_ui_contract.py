from __future__ import annotations

from pathlib import Path


def test_high_profile_ui_is_explicit_versioned_and_never_persisted():
    root = Path(__file__).resolve().parents[1]
    theme = (root / "static/theme.js").read_text(encoding="utf-8")
    css = (root / "static/model-profile.css").read_text(encoding="utf-8")

    assert 'const ACK_VERSION="contributor-v1"' in theme
    assert 'const PROFILE_HEADER="X-Padiem-Model-Profile"' in theme
    assert 'const ACK_HEADER="X-Padiem-High-Contributor-Ack"' in theme
    assert 'VALID_PROFILES=["low","medium","high"]' in theme
    assert 'selectedProfile="medium"' in theme
    assert "HIGH 사용 전 데이터 안내" in theme
    assert "개인정보·기밀정보·첨부 문서·프로젝트 자료" in theme
    assert "파일·프로젝트·웹 도구가 없는 일반 텍스트 질문" in theme
    assert "referenceContextActive" in theme
    assert "newChat.addEventListener" in theme
    assert "localStorage" not in theme
    assert "sessionStorage" not in theme
    assert "indexedDB" not in theme
    assert "document.cookie" not in theme
    assert ".model-profile-select" in css
    assert ".high-contributor-dialog" in css


def test_profile_fetch_guard_installs_before_later_feature_wrappers():
    root = Path(__file__).resolve().parents[1]
    theme = (root / "static/theme.js").read_text(encoding="utf-8")
    marker = "// Install synchronously while theme.js is evaluated."
    assert marker in theme
    marker_index = theme.index(marker)
    immediate_install = theme.index("installFetchGuard();", marker_index)
    init_index = theme.index("function init(){", immediate_install)
    assert immediate_install < init_index
    init_block = theme[init_index:]
    assert "installContextObserver();\n    installFetchGuard();" not in init_block


def test_profile_ui_uses_dom_construction_not_html_injection():
    root = Path(__file__).resolve().parents[1]
    theme = (root / "static/theme.js").read_text(encoding="utf-8")
    assert ".innerHTML" not in theme
    assert "insertAdjacentHTML" not in theme
    assert "document.write" not in theme
