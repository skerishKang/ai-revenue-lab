"""Static/security contracts for the Padiem Chat -> canonical B66 UI bridge (#3313).

#8060: 원문 read는 _support(b66_quote_bridge_source)가 담당하고, 계약은
이름붙인 팩트( Missing-token 목록·불리언·개수·블록 순서)로 단언한다.
"""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings

from _support.b66_quote_bridge_source import (  # noqa: E402
    asset_facts,
    authority_facts,
    iframe_guard_facts,
    index_facts,
    launcher_facts,
    linked_pc_facts,
    preview_facts,
    startup_facts,
)


def test_b66_quote_runtime_url_is_https_root_only_and_default_off() -> None:
    assert Settings.from_values().b66_quote_base_url is None
    configured = Settings.from_values(
        b66_quote_base_url="https://quick.example.test/"
    )
    assert configured.b66_quote_base_url == "https://quick.example.test"

    with pytest.raises(ConfigError, match="https"):
        Settings.from_values(b66_quote_base_url="http://quick.example.test")
    with pytest.raises(ConfigError, match="path"):
        Settings.from_values(
            b66_quote_base_url="https://quick.example.test/some/path"
        )
    with pytest.raises(ConfigError):
        Settings.from_values(
            b66_quote_base_url="https://user:pass@quick.example.test"
        )


def test_index_loads_hidden_quote_bridge_before_capability_projection() -> None:
    facts = index_facts()
    assert facts["css_ref"] is True
    assert facts["js_ref"] is True
    assert facts["js_before_capabilities"] is True
    # Manual merge-forward must preserve real HTML newlines. A literal "\\n"
    # becomes visible body text and can shift visual layout by one line.
    assert facts["newline_artifacts"] == []


def test_quote_ui_bridge_does_not_duplicate_quote_authorities_or_persist_skill() -> None:
    facts = authority_facts()
    assert facts["forbidden_tokens"] == []
    assert facts["hardcoded_host"] is False
    assert facts["env_var"] is False
    assert facts["missing_endpoints"] == []


def test_quote_ui_bridge_uses_exact_iframe_source_and_origin() -> None:
    assert iframe_guard_facts()["missing_guards"] == []


def test_signed_out_startup_is_network_silent_for_b66() -> None:
    facts = startup_facts()
    # #6100: signedIn comes from the capability event; refresh() only on it.
    assert facts["signed_in_assignment"] is True
    assert facts["refresh_on_signed_in"] is True
    assert facts["eager_startup"] is False
    # API access is centralized behind refresh/readJson rather than eager top-level fetch.
    assert facts["runtime_config_reads"] == 1


def test_launcher_stays_hidden_without_a_runtime_skills_or_a_linked_pc() -> None:
    facts = launcher_facts()
    # #6056: one condition, and the PC flag it reads. Nothing else may turn the
    # launcher on: no runtime, no saved skill and no linked PC keeps it hidden.
    for key in ("hidden_rule", "disabled_rule", "skills_assignment", "pc_flag_init", "linked_flag_rule"):
        assert facts[key] is True


def test_a_linked_pc_alone_shows_the_launcher_for_its_own_excel_form() -> None:
    facts = linked_pc_facts()
    # #5895: with a linked PC and no saved skill the screen still opens, says what it
    # is for, and the skill-only controls step aside so the PC form is the action.
    assert facts["missing_rules"] == []


def test_quote_ui_bridge_loads_only_bounded_private_quote_assets() -> None:
    facts = asset_facts()
    assert facts["missing_rules"] == []
    assert facts["data_uri"] is True
    assert facts["forbidden_tokens"] == []


def test_quote_preview_is_created_only_after_successful_request_and_never_same_origin() -> None:
    facts = preview_facts()
    assert facts["iframe_in_ensure"] is False
    assert facts["iframe_in_creation"] is True
    assert facts["referrer_policy"] is True
    assert facts["sandbox"] is True
    assert facts["assets_before_frame"] is True
    assert facts["frame_before_wait"] is True
    assert facts["same_origin_guard"] is True
    assert facts["source_guard"] is True
    assert facts["origin_guard"] is True
