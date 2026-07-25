"""Regression contracts for the Business 14 developer-console localization."""

from pathlib import Path

from app.pilot.locale import Locale, gettext


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TEMPLATE = APP_ROOT / "templates" / "workspace.html"
BASE_TEMPLATE = APP_ROOT / "templates" / "base.html"

CONSOLE_KEYS = (
    "workspace.console_crumb",
    "workspace.console_eyebrow",
    "workspace.runtime_metadata",
    "workspace.runtime",
    "workspace.key_mode",
    "workspace.registry_invalid_badge",
    "workspace.requests_blocked",
    "workspace.status_ready",
    "workspace.status_not_configured",
    "workspace.metrics",
    "workspace.session_policy",
    "workspace.connection_settings",
    "workspace.provider_routing",
    "workspace.cost_account",
    "workspace.security_policy",
    "workspace.security_provider_reset",
    "workspace.security_no_persistence",
    "workspace.conversation_session",
    "workspace.session_workspace",
    "workspace.request_response_stream",
    "workspace.input_hint",
)


def test_console_translation_keys_resolve_in_both_locales() -> None:
    for key in CONSOLE_KEYS:
        korean = gettext(key, Locale.KO)
        english = gettext(key, Locale.EN)
        assert korean and korean != key
        assert english and english != key


def test_console_has_korean_first_and_english_labels() -> None:
    assert gettext("workspace.console_eyebrow", Locale.KO) == "개발자 콘솔"
    assert gettext("workspace.console_eyebrow", Locale.EN) == "Developer Console"
    assert gettext("workspace.connection_settings", Locale.KO) == "연결 설정"
    assert gettext("workspace.connection_settings", Locale.EN) == "Connection settings"
    assert gettext("workspace.session_workspace", Locale.KO) == "세션 작업공간"
    assert gettext("workspace.session_workspace", Locale.EN) == "Session workspace"


def test_console_templates_do_not_hardcode_localized_interface_labels() -> None:
    content = WORKSPACE_TEMPLATE.read_text(encoding="utf-8")
    base = BASE_TEMPLATE.read_text(encoding="utf-8")

    for hardcoded in (
        "Workspace / Session Console",
        "Developer Console",
        "Connection settings",
        "Session workspace",
        "Cost and account",
        "Security policy",
        "Enter to send · Shift+Enter for line break",
    ):
        assert hardcoded not in content

    assert "Developer Console" not in base
    assert '_("workspace.console_eyebrow")' in base
