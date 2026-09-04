from __future__ import annotations

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
INTERACTION = APP_ROOT / "static" / "interaction-polish.js"
INTERACTION_CSS = APP_ROOT / "static" / "interaction-polish.css"
A11Y = APP_ROOT / "static" / "a11y.js"
INDEX = APP_ROOT / "static" / "index.html"
OUTPUTS = APP_ROOT / "static" / "outputs.js"
EXPORT = APP_ROOT / "static" / "conversation-export.js"


def test_interaction_polish_is_presentation_only_and_public_safe() -> None:
    source = INTERACTION.read_text(encoding="utf-8")
    assert 'ATTACHMENT_LOADING: "attachment_loading"' in source
    assert 'PREPARING: "preparing"' in source
    assert 'STREAMING: "streaming"' in source
    assert 'CANCELLING: "cancelling"' in source
    assert 'new Set(["completed", "failed", "cancelled", "timed_out"])' in source
    assert "요청을 준비하고 있습니다." in source
    assert "답변을 전달하고 있습니다." in source
    assert "답변 생성을 취소하고 있습니다." in source
    assert "파일을 안전하게 확인하고 있습니다." in source

    forbidden = (
        "fetch(",
        "/api/",
        "provider",
        "model_id",
        "tool_arguments",
        "hidden_reasoning",
        "chain_of_thought",
        "fallback_policy",
    )
    lowered = source.lower()
    for token in forbidden:
        assert token.lower() not in lowered


def test_terminal_copy_and_focus_recovery_are_distinct_without_new_execution_semantics() -> None:
    source = INTERACTION.read_text(encoding="utf-8")
    assert 'state === "completed" ? "true" : "false"' in source
    assert 'state !== "timed_out"' in source
    assert "응답 시간이 지났습니다." in source
    assert "정해진 시간 안에 응답이 완료되지 않았습니다." in source
    assert "focusComposer" in source
    assert 'cancelButton.setAttribute("aria-busy", "true")' in source
    assert 'retry.setAttribute("aria-busy", "true")' in source
    assert 'retry.textContent = copy("다시 시도 중…", "Retrying…")' in source


def test_terminal_actions_continue_to_use_existing_lifecycle_safety_contracts() -> None:
    outputs = OUTPUTS.read_text(encoding="utf-8")
    export = EXPORT.read_text(encoding="utf-8")
    interaction = INTERACTION.read_text(encoding="utf-8")

    assert "lifecycleApi().isCompleted(article)" in outputs
    assert "if (!lifecycleApi().isCompleted(article))" in outputs
    assert "lifecycleApi().isCompleted(article)" in export
    assert "hasIncompleteAssistant()" in export
    assert "data-terminal-actions-safe" not in outputs
    assert "data-terminal-actions-safe" not in export
    assert "PadiemChatLifecycle.set" not in interaction
    assert "PadiemChatTransport" not in interaction


def test_attachment_busy_and_accessibility_contracts_are_explicit() -> None:
    source = INTERACTION.read_text(encoding="utf-8")
    css = INTERACTION_CSS.read_text(encoding="utf-8")
    assert 'attachmentInput.addEventListener("change"' in source
    assert "guardAttachmentControls" in source
    assert "sendButton.disabled = true" in source
    assert 'form.setAttribute("aria-busy"' in source
    assert 'status.setAttribute("aria-live", "polite")' in source
    assert "min-height: 44px" in css
    assert "focus-visible" in css
    assert "prefers-reduced-motion" in css


def test_interaction_polish_loads_after_app_without_reordering_authority_layers() -> None:
    a11y = A11Y.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    assert 'interactionPolish.src = "./interaction-polish.js"' in a11y
    assert 'interactionPolish.dataset.interactionPolishLoader = "true"' in a11y
    assert index.index('<script src="./app.js"></script>') < index.index('<script src="./a11y.js"></script>')
    assert index.index('<script src="./chat-transport.js"></script>') < index.index('<script src="./app.js"></script>')
