from pathlib import Path


def sources():
    root = Path(__file__).resolve().parents[1]
    return (
        (root / "static/locale.js").read_text(encoding="utf-8"),
        (root / "static/outputs.js").read_text(encoding="utf-8"),
        (root / "static/theme.js").read_text(encoding="utf-8"),
        (root / "static/attachment-capabilities.js").read_text(encoding="utf-8"),
    )


def test_locale_is_url_authoritative_without_hidden_browser_storage():
    locale, _, _, _ = sources()
    assert 'searchParams.get("lang")' in locale
    assert 'searchParams.set("lang", lang)' in locale
    assert "history.replaceState" in locale
    assert 'window.addEventListener("popstate"' in locale
    assert 'apply(getUrlLocale() || "ko", false)' in locale
    assert 'apply("ko")' not in locale
    assert "localStorage" not in locale
    assert "sessionStorage" not in locale
    assert "document.cookie" not in locale


def test_locale_change_is_projection_only_and_does_not_reset_chat_state():
    locale, _, _, _ = sources()
    assert 'document.documentElement.lang = locale' in locale
    assert 'padiem:localechange' in locale
    assert "conversationState.reset" not in locale
    assert "location.reload" not in locale
    assert "window.location.assign" not in locale


def test_dynamic_glass_and_accessibility_copy_are_localized():
    locale, _, theme, _ = sources()
    assert 'data-theme-value="padiem-glass"' in locale
    assert 'data-glass-variant-value="female"' in locale
    assert 'data-glass-variant-value="male"' in locale
    assert '"glass-a": "배경 A"' in locale
    assert '"glass-a": "Background A"' in locale
    assert '"glass-b": "배경 B"' in locale
    assert '"glass-b": "Background B"' in locale
    assert '"main-menu": "Main menu"' in locale
    assert '"settings-close": "Close settings"' in locale
    assert '"attachment-remove": "Remove attachment"' in locale
    assert '"send": "Send message"' in locale
    assert '"export-aria": "Export the current conversation as a text file"' in locale
    assert 'const GLASS_VARIANTS=["female","male"]' in theme


def test_attachment_copy_stays_on_current_capability_projection():
    locale, _, _, capabilities = sources()
    assert "attachmentCapabilities.copy(lang)" in locale
    assert "attachmentCapabilities.accept" in locale
    for label in ["JPEG", "PNG", "WebP", "TXT", "Markdown", "CSV", "JSON", "PDF", "DOCX", "PPTX", "XLSX"]:
        assert f'label: "{label}"' in capabilities


def test_saved_outputs_auth_is_not_coupled_to_korean_button_text():
    locale, outputs, _, _ = sources()
    assert 'button.dataset.authenticated = "true"' in locale
    assert 'button.dataset.authenticated = "false"' in locale
    assert 'loginButton.dataset.authenticated === "true"' in outputs
    assert 'textContent.trim() === "로그아웃"' not in outputs


def test_locale_switch_updates_url_but_not_conversation_or_attachment_authority():
    locale, _, _, _ = sources()
    assert "persistLocale(locale)" in locale
    assert 'button.dataset.localeValue' in locale
    assert "selectedAttachment" not in locale
    assert "conversationEpoch" not in locale
    assert "activeProject =" not in locale


def test_first_party_dynamic_controls_have_english_projection():
    locale, _, _, _ = sources()
    required = [
        '"project-delete": "Delete project"',
        '"manage": "Manage"',
        '"retry": "Try again"',
        '"timeout": "Response timed out"',
        '"connection-error": "Connection error"',
        '"answer-actions": "Answer actions"',
        '"csv-download": "Download CSV"',
        '"sources": "Sources"',
        '"export": "Export conversation"',
    ]
    for marker in required:
        assert marker in locale
