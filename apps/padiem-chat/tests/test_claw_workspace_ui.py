"""#2114 ACT-1 — Claw first-class workspace UI contracts (static, bounded).

These guard the design decisions accepted in the ACT-0 review:
- the modal is no longer the primary Claw surface;
- a data-state="claw" workspace replaces it inside the shared shell;
- the shared bottom composer is the natural-language input (kept visible,
  >=16px to avoid iOS focus zoom) — #2532 continuity pass;
- results render as a compact card, never a raw inline document;
- document/DOCX affordances stay honestly disabled (no fake success);
- Chat vs Claw navigation exposes aria-current active state.

#8060: 원문 read는 _support(claw_workspace_ui_source)가 담당하고, 계약은
이름붙인 팩트·개수·부재 목록으로 단언한다.
"""

from __future__ import annotations

from _support.claw_workspace_ui_source import (  # noqa: E402
    action_facts,
    affordance_facts,
    composer_facts,
    modal_facts,
    nav_facts,
    preview_facts,
    result_facts,
    shell_state_facts,
    single_h1_facts,
    touch_facts,
)


def test_modal_is_no_longer_the_primary_claw_surface() -> None:
    facts = modal_facts()
    assert facts["unexpected"] == []
    assert facts["missing"] == []
    # The sidebar button is now a workspace destination, not a dialog trigger.
    assert facts["dialog_attrs"] == []


def test_workspace_is_a_first_class_shell_state() -> None:
    facts = shell_state_facts()
    # R5 A10: the Claw entry state write lives in chat-nav-module.js.
    assert facts["nav_state_write"] is True
    assert facts["missing_css"] == []
    # Chat/home canvas is hidden while the Claw workspace owns the panel,
    # but the shared bottom composer stays visible (#2532 continuity).
    assert facts["unexpected_css"] == []


def test_natural_language_input_is_the_composer_and_zoom_safe() -> None:
    facts = composer_facts()
    # #2532: the hero textarea is gone; #messageInput is the Claw request input
    # and the intake form is a compact mode bar inside the composer wrap.
    assert facts["unexpected_markup"] == []
    assert facts["missing_markup"] == []
    assert facts["missing_css"] == []
    assert facts["workspace_font_16"] is True
    assert facts["intake_font_16"] is True
    # The disclosure fields must not regress to the old 13.6px form controls.
    assert facts["old_small_control"] is False


def test_actions_are_optional_overrides_not_mandatory_cards() -> None:
    facts = action_facts()
    assert facts["chips_present"] is True
    assert facts["action_count"] >= 4
    assert facts["aria_pressed"] is True
    # The old mandatory action-card grid is gone.
    assert facts["old_grid"] is False


def test_result_is_a_compact_card_not_raw_inline_document() -> None:
    facts = result_facts()
    assert facts["missing_markup"] == []
    # The result body is capped and scrollable rather than expanding a full doc.
    assert facts["max_height"] is True


def test_document_affordances_stay_honestly_disabled() -> None:
    facts = affordance_facts()
    # No fabricated download/open success: the result actions render disabled.
    assert facts["disabled_action_present"] is True
    # The five never-wired coming-soon controls are gone, not merely disabled.
    assert facts["old_control_present"] is False


def test_chat_claw_active_navigation_state() -> None:
    facts = nav_facts()
    assert facts["aria_current_set"] is True
    assert facts["missing_css"] == []


def test_primary_touch_targets_are_at_least_44px() -> None:
    facts = touch_facts()
    assert facts["min_44"] is True
    assert facts["min_48"] is True  # generate button


def test_workspace_preserves_single_h1_contract() -> None:
    # The canonical accessibility QA uses a strict locator("h1"); the Claw
    # workspace title must not introduce a second h1 alongside the home h1.
    facts = single_h1_facts()
    assert facts["h1_count"] == 1
    assert facts["missing_markup"] == []


def test_preview_endpoint_and_safe_dom_sinks_preserved() -> None:
    facts = preview_facts()
    assert facts["preview_endpoint"] is True
    assert facts["text_content_sink"] is True
    assert facts["inner_html_present"] is False
    assert facts["forbidden_tokens"] == []
