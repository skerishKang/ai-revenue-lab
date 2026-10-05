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
