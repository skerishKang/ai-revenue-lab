"""#3531 — general Claw requests stay in Claw; quotation only on explicit intent.

Root cause (proven in app.js): while shell data-state was "claw", the shared
composer submit handler diverted Enter into clawManualForm.requestSubmit(),
and the manual form's default action carrier is quote. Every generic request
typed in the Claw workspace therefore entered the quotation-draft workflow
(견적서 초안 / DOCX / 메모리 저장 후보) instead of the general conversation.

These contracts pin the repair at the static boundary:

- the composer submit handler routes to submitPrompt unconditionally: no
  shell-state branch, no manual-form diversion;
- the quotation workflow remains reachable only through the manual form's
  own explicit submit (초안 만들기) with its action selector;
- the general chat transport (/api/chat/stream) is untouched.

#8060 58차: 원문 read는 _support/claw_general_routing_view가 담당하고, 단언은
파싱된 선택자·이름붙은 팩트·계산 값으로 확인한다(의미 약화 없음).
"""

from __future__ import annotations

from _support.claw_general_routing_view import (  # noqa: E402
    composer_submit_facts,
    conversation_facts,
    locale_facts,
    manual_entry_facts,
    manual_workflow_facts,
    memory_facts,
    static_diversion_tokens,
    styles_facts,
    transport_facts,
    view_facts,
    workspace_selector_has,
)


def test_generic_composer_submit_reaches_general_chat_unconditionally() -> None:
    facts = composer_submit_facts()
    # The only outbound call from the composer is the general conversation.
    assert facts["submits_prompt"] is True
    # No shell-state fork and no manual-form diversion remain inside it.
    assert facts["forbidden"] == []


def test_no_composer_diversion_anywhere_in_static() -> None:
    # The hijack existed in exactly one place; it must not reappear under a
    # different spelling elsewhere in the composer path.
    assert static_diversion_tokens() == []


def test_quotation_workflow_requires_explicit_manual_submit() -> None:
    # The manual form keeps its own submit listener posting the selected
    # action to preview; the execute button posts to execute. Both are
    # user-invoked controls, never the composer default.
    facts = manual_workflow_facts()
    for key in ("form_submit_listener", "preview_fetch", "execute_fetch", "action_value"):
        assert facts[key] is True
    assert facts["missing_actions"] == []


def test_general_chat_transport_untouched() -> None:
    # The general path the composer now always takes still exists end to end.
    # B7: requestAnswer lives in the streaming module and is reached through
    # the registry (app.provide("streaming")) — no app.js forwarder remains.
    facts = transport_facts()
    for key in (
        "stream_fetch", "chat_fetch", "app_request_answer_absent",
        "streaming_provided", "request_answer_in_stream",
        "streaming_answer_call", "submit_prompt_definition",
    ):
        assert facts[key] is True


def test_claw_default_view_is_general_not_manual() -> None:
    # #3531 UI hierarchy: opening Claw lands on the general conversation
    # view. The document workflow is a separate explicit view, never the
    # default. Auth loss also falls back to general, never to manual.
    facts = view_facts()
    for key in (
        "general_view_set", "general_manual_hidden", "manual_view_set",
        "manual_visible", "session_bind", "auth_guard_before_reset",
    ):
        assert facts[key] is True
    # R5 A10: openClawWorkspace moved to chat-nav-module.js - the one general reset lives there.
    assert facts["nav_general_count"] == 1
    # With the inbox gone, only the automation fallback still resets to general.
    assert facts["general_reset_count"] == 1
    assert facts["nav_manual_count"] == 1


def test_manual_workflow_is_explicitly_reachable_only() -> None:
    # A visible entry control opens the manual view; nothing else does. It
    # lives in the fixed composer wrap (always on screen), not in the
    # workspace canvas, so geometry parity with Chat Home is preserved.
    facts = manual_entry_facts()
    for key in (
        "entry_bar_id", "entry_button_id", "locale_key", "bar_in_wrap",
        "click_listener", "wire_call", "workspace_title",
    ):
        assert facts[key] is True


def test_general_view_hides_workspace_canvas() -> None:
    # Geometry parity forces the workspace canvas hidden in general view
    # (like manual): any in-flow header above the thread would push the
    # conversation down. The entry bar carries explicit access instead.
    assert workspace_selector_has('.claw-workspace[data-view="general"]') is True
    assert manual_entry_facts()["entry_bar_lookup_in_nav"] is True


def test_manual_chrome_hidden_unless_manual_view() -> None:
    # Workflow chip, workflow help, and the manual-entry control swap by
    # view: chip/help only in manual, entry control everywhere else.
    for selector in (
        '.claw-workspace:not([data-view="manual"]) .claw-workspace-chip',
        '.claw-workspace:not([data-view="manual"]) .claw-workspace-help',
        '.claw-entry-bar[hidden]',
    ):
        assert workspace_selector_has(selector) is True
    # The manual result empty/hint copy is workflow-view-only. The result
    # card and memory surfaces keep their own explicit reveal logic.
    for element_id in ("#clawResultEmpty", "#clawResultHint", "#clawExecuteHint"):
        assert workspace_selector_has(element_id) is True


def test_conversation_stays_primary_in_general_view() -> None:
    # Only inbox/automation take over the canvas and hide the conversation.
    # The general view keeps the primary result surface visible.
    assert workspace_selector_has(':not([data-view="manual"]):not([data-view="general"])') is True


def test_claw_default_copy_is_general() -> None:
    # The Claw tagline must not present a quotation-only product. Values
    # changed (keys kept for locale parity); the old draft-framing copy
    # must be gone in both languages.
    facts = locale_facts()
    for key in ("old_ko_absent", "old_en_absent", "new_ko", "new_en"):
        assert facts[key] is True
    assert facts["manual_entry_keys"] >= 2


def test_memory_surfaces_stay_secondary() -> None:
    # Memory review and approved memory are hidden by default and render
    # only after explicit workflow action — never ahead of the primary
    # conversation result.
    facts = memory_facts()
    for element_id in ("clawMemoryReview", "clawApprovedMemory"):
        assert facts["hidden_by_id"][element_id] is True
    # R5 A2: 1 definition in chat-memory-module.js + 1 app.renderMemoryProposalReview call in app.js.
    assert facts["definition_count"] == 1
    assert facts["app_call_count"] == 1
    assert facts["total_count"] == 2


def test_sticky_bottom_reserve_intact() -> None:
    # The fixed bottom stack (composer; manual form hidden by default) keeps
    # its scroll reserves, so recent runs and body content are not clipped.
    styles = styles_facts()
    assert styles["position_fixed"] is True
    assert styles["bottom_zero"] is True
    # #5014/#5260: the reserve follows the measured composer clearance. The
    # former fixed 280px inset survives only as its fallback, never as the
    # sole padding value.
    conversation = conversation_facts()
    for key in ("calc_padding", "clearance_fallback", "keyboard_inset", "no_fixed_280"):
        assert conversation[key] is True
    assert styles["overflow_y_auto"] is True
