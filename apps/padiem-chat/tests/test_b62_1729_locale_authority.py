from __future__ import annotations

from _support.locale_authority import (
    ATTACHMENT_COPY,
    AUTH_FLAGS,
    CAPABILITY_LABELS,
    GLASS_TOKENS,
    LOCALE_SWITCH,
    PROJECTION,
    REQUIRED_LOCALE_PAIRS,
    URL_AUTHORITY,
    facts,
)


def test_locale_is_url_authoritative_without_hidden_browser_storage():
    result = facts()
    assert set(result["url_authority"]) == set(URL_AUTHORITY)
    assert result["url_forbidden"] == ()


def test_locale_change_is_projection_only_and_does_not_reset_chat_state():
    result = facts()
    assert set(result["projection"]) == set(PROJECTION)
    assert result["projection_forbidden"] == ()


def test_dynamic_glass_and_accessibility_copy_are_localized():
    result = facts()
    assert set(result["glass_tokens"]) == set(GLASS_TOKENS)
    assert set(REQUIRED_LOCALE_PAIRS).issubset(result["locale_pairs"])
    assert result["glass_variants"] == ('"female","male"',)


def test_attachment_copy_stays_on_current_capability_projection():
    result = facts()
    assert set(result["attachment_copy"]) == set(ATTACHMENT_COPY)
    assert set(CAPABILITY_LABELS).issubset(result["capability_labels"])


def test_saved_outputs_auth_is_not_coupled_to_korean_button_text():
    result = facts()
    assert set(result["auth_flags"]) == set(AUTH_FLAGS)
    assert result["outputs_auth"] is True
    assert result["outputs_korean_button"] is False


def test_locale_switch_updates_url_but_not_conversation_or_attachment_authority():
    result = facts()
    assert set(result["locale_switch"]) == set(LOCALE_SWITCH)
    assert result["switch_forbidden"] == ()


def test_first_party_dynamic_controls_have_english_projection():
    result = facts()
    assert set(REQUIRED_LOCALE_PAIRS).issubset(result["locale_pairs"])
