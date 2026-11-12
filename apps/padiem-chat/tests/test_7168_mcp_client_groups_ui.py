"""#7168: advanced settings groups external AI connections by AI client.

The default view of the 고급 설정 → 연결된 AI page is one card per AI client:
name, connection count, device count and last-used time, plus a single
"연결 해지" button that revokes every grant of that AI at once. The previous
per-token list is not deleted; it is collapsed under 자세히. These contracts
read behavior (selector lists, declarations, locale-key linkage), not bytes.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

from css_rules import (
    declaration,
    find_rules_with_selector,
    parse_rules,
    rule_selector_list_contains,
)

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / "static"
NODE = shutil.which("node")
POLISH_CSS = STATIC / "padiem-chat-ui-polish.css"
SETTINGS_CSS = STATIC / "mcp-gateway-settings.css"
CONSOLIDATED_CSS = STATIC / "padiem-settings.css"  # #7476-14
SOURCE = STATIC / "mcp-gateway-settings.js"
HTML = STATIC / "index.html"
LOCALE = STATIC / "locale.js"
READ = lambda path: path.read_text(encoding="utf-8")  # noqa: E731


def _ai_section() -> str:
    html = READ(HTML)
    start = html.index('id="mcpGatewaySettings"')
    end = html.index('data-advanced-block="account"', start)
    return html[start:end]


def _locale_pair() -> tuple[str, str]:
    locale = READ(LOCALE)
    ko, en = locale.split("    en: {", 1)
    return ko, en


def test_ai_connections_default_to_grouped_cards_with_legacy_list_collapsed() -> None:
    section = _ai_section()
    assert 'id="mcpGatewayClientsList"' in section
    assert "mcp-gateway-clients" in section
    legacy = section.index('id="mcpGatewayLegacyList"')
    token_list = section.index('id="mcpGatewayList"')
    assert legacy < token_list, "the legacy per-token list lives inside the details block"
    details_open = section.rindex("<details", 0, legacy)
    details_close = section.index("</details>", details_open)
    assert token_list < details_close
    open_tag = section[details_open:section.index(">", details_open)]
    assert " open" not in open_tag, "the legacy list starts collapsed"


def test_ai_grouped_copy_is_linked_to_locale_keys_in_both_languages() -> None:
    ko, en = _locale_pair()
    ko_keys = set(re.findall(r'"(mcp-ai-[a-z-]+)":', ko))
    en_keys = set(re.findall(r'"(mcp-ai-[a-z-]+)":', en))
    assert ko_keys == en_keys
    assert {
        "mcp-ai-empty", "mcp-ai-load-error", "mcp-ai-revoke-confirm",
        "mcp-ai-revoked", "mcp-ai-retry", "mcp-ai-connection-count",
        "mcp-ai-device-count", "mcp-ai-details",
    } <= ko_keys
    for key in ("mcp-ai-connection-count", "mcp-ai-device-count", "mcp-ai-revoke-confirm"):
        assert "{count}" in ko.split(f'"{key}":', 1)[1].split("\n", 1)[0]
        assert "{count}" in en.split(f'"{key}":', 1)[1].split("\n", 1)[0]
    source = READ(SOURCE)
    for key in ko_keys:
        assert f'"{key}"' in source, f"declared locale key {key} is never used"
    html = READ(HTML)
    assert 'data-locale-key="mcp-ai-details"' in html


def test_primary_action_reuses_the_shared_primary_navy_rule() -> None:
    rules = parse_rules(READ(POLISH_CSS))
    primary = find_rules_with_selector(rules, ".claw-generate-button")
    assert len(primary) == 3, "one decision in base, hover and focus states"
    for rule in primary:
        assert rule_selector_list_contains(rule, ".mcp-ai-primary:not(:disabled)")
    base = next(
        rule for rule in primary
        if not any(s.endswith((":hover", ":focus-visible")) for s in rule.selectors)
    )
    # #7187 R3: the numbers live in padiem-tokens.css.
    assert declaration(base, "background") == "var(--primary-bg)"
    assert declaration(base, "border-color") == "var(--primary-border)"
    assert declaration(base, "color") == "#fff"
    html = READ(HTML)
    assert re.search(r'class="settings-action mcp-ai-primary" id="mcpGatewayIssue"', html)
    source = READ(SOURCE)
    assert "mcp-ai-primary" in source, "the AI-card retry action joins the same primary rule"


def test_revoke_button_reuses_the_danger_action_style_not_the_primary_fill() -> None:
    source = READ(SOURCE)
    assert re.search(
        r'"settings-action settings-action-danger mcp-gateway-client-revoke"', source
    ), "the revoke action keeps the existing danger style"
    rules = parse_rules(READ(CONSOLIDATED_CSS))
    danger = find_rules_with_selector(rules, ".settings-action-danger")
    assert danger, "the danger action style still exists in the settings sheet"
    for rule in find_rules_with_selector(rules, ".claw-generate-button"):
        assert not rule_selector_list_contains(rule, ".mcp-gateway-client-revoke"), (
            "a destructive revoke must not wear the primary fill"
        )


def test_grouped_cards_keep_the_theme_surface() -> None:
    """A hardcoded white card hid every label in the dark theme."""
    rules = parse_rules(READ(SETTINGS_CSS))
    card = find_rules_with_selector(rules, ".mcp-gateway-client-card")
    assert card
    assert declaration(card[0], "background") is None


def test_dark_and_cinematic_revoke_surfaces_stay_legible() -> None:
    """The light translucent action fill put light danger text on light fill."""
    rules = parse_rules(READ(SETTINGS_CSS))
    selectors = [
        selector
        for rule in rules
        if any("mcp-gateway-client-revoke" in selector for selector in rule.selectors)
        for selector in rule.selectors
    ]
    assert 'html[data-theme="dark"] .mcp-gateway-client-revoke' in selectors
    assert 'html[data-theme="cinematic"] .mcp-gateway-client-revoke' in selectors


def test_ai_grouped_screen_states_are_distinct() -> None:
    source = READ(SOURCE)
    for key in ("mcp-ai-empty", "mcp-ai-load-error", "mcp-settings-login"):
        assert f'"{key}"' in source
    # The retry control exists only in the failure branch, not in empty/login.
    assert "mcp-gateway-client-error" in source
    assert "mcp-gateway-client-retry" in source


@pytest.mark.skipif(NODE is None, reason="node is required for the DOM harness")
def test_grouped_ai_cards_in_the_settings_dom_harness() -> None:
    result = subprocess.run(
        [NODE, str(HERE / "mcp_gateway_settings_harness.js"), str(SOURCE)],
        text=True, encoding="utf-8", capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MCP_GATEWAY_SETTINGS=PASS" in result.stdout
    assert result.stdout.count("MCP_GATEWAY_CHECK") == 22
    for label in (
        "external AI connections render as AI-client bundles",
        "revoking one AI client bundle removes it and refreshes the list",
        "cancelled confirmation keeps the AI client and sends no DELETE",
        "empty AI list shows the empty state",
        "AI load error renders an error state with retry",
        "401 on clients API shows the login state",
    ):
        assert label in result.stdout
