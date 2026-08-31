from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_PATH = ROOT / "static" / "outputs.js"


def _source() -> str:
    return OUTPUTS_PATH.read_text(encoding="utf-8")


def test_saved_outputs_uses_lifecycle_not_disabled() -> None:
    src = _source()
    assert "window.PadiemChatLifecycle" in src
    assert "lifecycleApi().isCompleted(article)" in src
    assert "padiem:message-lifecycle" in src
    # Old approach must not be present
    assert "messageInput" not in src
    assert "canEnhanceAnswers" not in src or "isCompleted" in src  # ensure lifecycle is used


def test_saved_outputs_not_created_for_incomplete() -> None:
    src = _source()
    # enhanceAssistantMessage must gate on isCompleted and remove if incomplete
    assert "function enhanceAssistantMessage(" in src
    enhance_start = src.index("function enhanceAssistantMessage(")
    enhance_end = src.index("function enhanceAllAnswers(", enhance_start)
    enhance = src[enhance_start:enhance_end]
    assert "if (!lifecycleApi().isCompleted(article))" in enhance
    assert "removeAnswerActions(article);" in enhance
    assert "if (article.dataset.outputActions === \"true\") return;" in enhance
    # Must check answerText excludes typing/error
    assert 'content.querySelector(".typing")' in enhance or 'answerText' in src
    # Must have removeAnswerActions helper
    assert "function removeAnswerActions(" in src


def test_saved_outputs_text_captured_only_after_completion() -> None:
    src = _source()
    enhance_start = src.index("function enhanceAssistantMessage(")
    enhance_end = src.index("function enhanceAllAnswers(", enhance_start)
    enhance = src[enhance_start:enhance_end]
    # Text must be captured after isCompleted check
    gate = enhance.index("if (!lifecycleApi().isCompleted(article))")
    capture = enhance.index("const text = answerText(article);")
    copy = enhance.index("copyText(text)")
    download = enhance.index("downloadText(text, titleFromText(text))")
    save = enhance.index("JSON.stringify({ title: titleFromText(text), content: text })")
    assert gate < capture < copy
    assert capture < download
    assert capture < save
    # Ensure lifecycle check also in click handlers for copy/download/save
    assert enhance.count("lifecycleApi().isCompleted(article)") >= 3


def test_saved_outputs_error_never_gets_actions_and_is_fail_closed() -> None:
    src = _source()
    # answerText must exclude typing/error
    assert "function answerText(" in src
    answer_start = src.index("function answerText(")
    answer_end = src.index("function feedbackButton(", answer_start)
    answer = src[answer_start:answer_end]
    assert 'content.querySelector(".typing")' in answer
    assert 'content.querySelector(".error-box")' in answer
    # If later becomes incomplete/error, actions are removed
    assert "removeAnswerActions(article);" in src
    # Enhance is called on lifecycle event, so later transition to failed will remove
    assert 'messageList.addEventListener("padiem:message-lifecycle", enhanceAllAnswers);' in src


def test_saved_outputs_restored_completed_remain_eligible() -> None:
    src = _source()
    # Restored messages are set to COMPLETED in app.js; outputs.js must treat them as eligible via isCompleted
    assert "lifecycleApi().isCompleted(article)" in src
    # enhanceAllAnswers is called initially and on lifecycle, so restored completed will get actions
    assert "enhanceAllAnswers();" in src
    assert "messageList.addEventListener" in src
    # Once enhanced, dataset flag prevents duplicate, but restored will be enhanced
    assert 'article.dataset.outputActions === "true"' in src


def test_saved_outputs_if_later_incomplete_actions_removed() -> None:
    src = _source()
    # The observer + lifecycle listener ensures fail-closed removal
    assert "new MutationObserver(enhanceAllAnswers);" in src or "MutationObserver" in src
    assert "padiem:message-lifecycle" in src
    # removeAnswerActions must delete dataset flag
    assert 'delete article.dataset.outputActions;' in src
    assert "article.querySelectorAll(\".answer-actions\")" in src
    # Save button hidden/disabled based on outputsReady and isCompleted
    assert "updateSaveButtons" in src
    assert "lifecycleApi().isCompleted(article)" in src
