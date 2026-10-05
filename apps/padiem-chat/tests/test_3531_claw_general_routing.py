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
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")


def _composer_submit_handler() -> str:
    start = APP.index('form.addEventListener("submit"')
    end = APP.index("\n  });", start)
    return APP[start:end]


def test_generic_composer_submit_reaches_general_chat_unconditionally() -> None:
    handler = _composer_submit_handler()
    # The only outbound call from the composer is the general conversation.
    assert "submitPrompt(input.value)" in handler
    # No shell-state fork and no manual-form diversion remain inside it.
    assert "clawManualForm" not in handler
    assert "dataset.state" not in handler
    assert "requestSubmit" not in handler


def test_no_composer_diversion_anywhere_in_static() -> None:
    # The hijack existed in exactly one place; it must not reappear under a
    # different spelling elsewhere in the composer path.
    assert "clawManualForm.requestSubmit()" not in APP


def test_quotation_workflow_requires_explicit_manual_submit() -> None:
    # The manual form keeps its own submit listener posting the selected
    # action to preview; the execute button posts to execute. Both are
    # user-invoked controls, never the composer default.
    assert 'clawManualForm.addEventListener("submit"' in APP
    assert 'fetch("/api/claw/manual-intake/preview"' in APP
    assert 'fetch("/api/claw/manual-intake/execute"' in APP
    assert "clawAction?.value" in APP
    for action in ('"quote"', '"order"', '"reply"', '"summary"'):
        assert action in INDEX


def test_general_chat_transport_untouched() -> None:
    # The general path the composer now always takes still exists end to end.
    assert 'fetch("/api/chat/stream"' in TRANSPORT
    assert 'fetch("/api/chat"' in TRANSPORT
    assert "async function requestAnswer(" in APP
    assert "requestStreamingAnswer(article, payload" in APP
    assert "async function submitPrompt(text, selectedSkill)" in APP


WORKSPACE_CSS = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")
STYLES_CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    start = APP.index(f"function {name}() {{")
    end = APP.index("\n  }", start)
    return APP[start:end]


def test_claw_default_view_is_general_not_manual() -> None:
    # #3531 UI hierarchy: opening Claw lands on the general conversation
    # view. The document workflow is a separate explicit view, never the
    # default. Auth loss also falls back to general, never to manual.
    general = _function_body("openClawWorkspace")
    assert 'clawWorkspace.dataset.view = "general"' in general
    assert "if (clawManualForm) clawManualForm.hidden = true;" in general
    manual = _function_body("openClawManual")
    assert 'clawWorkspace.dataset.view = "manual"' in manual
    assert "if (clawManualForm) clawManualForm.hidden = false;" in manual
    assert APP.count('clawWorkspace.dataset.view = "general"') == 1
    assert APP.count('workspace.dataset.view = "general"') == 2
    assert APP.count('clawWorkspace.dataset.view = "manual"') == 1


def test_manual_workflow_is_explicitly_reachable_only() -> None:
    # A visible entry control opens the manual view; nothing else does.
    assert 'id="clawManualEntryButton"' in INDEX
    assert 'data-locale-key="claw-manual-entry"' in INDEX
    assert 'clawManualEntryButton.addEventListener("click", openClawManual)' in APP
    # The workspace header keeps its identity; the entry control is new.
    assert 'id="clawWorkspaceTitle"' in INDEX


def test_manual_chrome_hidden_unless_manual_view() -> None:
    # Workflow chip, workflow help, and the manual-entry control swap by
    # view: chip/help only in manual, entry control everywhere else.
    assert ".claw-workspace:not([data-view=\"manual\"]) .claw-workspace-chip" in WORKSPACE_CSS
    assert ".claw-workspace:not([data-view=\"manual\"]) .claw-workspace-help" in WORKSPACE_CSS
    assert '.claw-workspace[data-view="manual"] #clawManualEntryButton' in WORKSPACE_CSS
    # The manual result empty/hint copy is workflow-view-only. The result
    # card and memory surfaces keep their own explicit reveal logic.
    assert "#clawResultEmpty" in WORKSPACE_CSS
    assert "#clawResultHint" in WORKSPACE_CSS
    assert "#clawExecuteHint" in WORKSPACE_CSS


def test_conversation_stays_primary_in_general_view() -> None:
    # Only inbox/automation take over the canvas and hide the conversation.
    # The general view keeps the primary result surface visible.
    assert ":not([data-view=\"manual\"]):not([data-view=\"general\"])" in WORKSPACE_CSS


def test_claw_default_copy_is_general() -> None:
    # The Claw tagline must not present a quotation-only product. Values
    # changed (keys kept for locale parity); the old draft-framing copy
    # must be gone in both languages.
    assert "견적서·발주서·답장 초안을 준비하는" not in LOCALE
    assert "to prepare quote, order, and reply drafts" not in LOCALE
    assert "Padiem AI 작업공간" in LOCALE
    assert "Padiem AI workspace" in LOCALE
    assert LOCALE.count('"claw-manual-entry": "') >= 2


def test_memory_surfaces_stay_secondary() -> None:
    # Memory review and approved memory are hidden by default and render
    # only after explicit workflow action — never ahead of the primary
    # conversation result.
    for marker in ('id="clawMemoryReview"', 'id="clawApprovedMemory"'):
        line = next(l for l in INDEX.splitlines() if marker in l)
        assert "hidden" in line, marker
    # Memory proposals render from exactly one call site: preview success.
    assert APP.count("renderMemoryProposalReview(") == 2


def test_sticky_bottom_reserve_intact() -> None:
    # The fixed bottom stack (composer; manual form hidden by default) keeps
    # its scroll reserves, so recent runs and body content are not clipped.
    assert "position: fixed" in STYLES_CSS
    assert "bottom: 0" in STYLES_CSS
    assert "padding-bottom: 280px" in WORKSPACE_CSS
    assert "overflow-y: auto" in WORKSPACE_CSS
