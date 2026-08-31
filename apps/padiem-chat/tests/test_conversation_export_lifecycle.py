from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = ROOT / "static" / "conversation-export.js"


def _source() -> str:
    return EXPORT_PATH.read_text(encoding="utf-8")


def test_export_uses_lifecycle_not_composer_disabled() -> None:
    src = _source()
    # Must use PadiemChatLifecycle authority, not old messageInput.disabled
    assert "window.PadiemChatLifecycle" in src
    assert "lifecycleApi().isCompleted(article)" in src
    assert "padiem:message-lifecycle" in src
    # Old approach must not be present
    assert "messageInput" not in src
    assert "requestInFlight" not in src
    assert 'messageInput.disabled' not in src


def test_export_skips_typing_error_and_incomplete_via_lifecycle() -> None:
    src = _source()
    # exportableAssistantText must gate on isCompleted and typing/error
    assert "function exportableAssistantText(" in src
    exportable_start = src.index("function exportableAssistantText(")
    exportable_end = src.index("function hasIncompleteAssistant(", exportable_start)
    helper = src[exportable_start:exportable_end]
    assert "lifecycleApi().isCompleted(article)" in helper
    assert 'content.querySelector(".typing")' in helper
    assert 'content.querySelector(".error-box")' in helper
    assert "visiblePlainText(content)" in helper

    # hasIncompleteAssistant and hasSettledAssistant must exist
    assert "function hasIncompleteAssistant(" in src
    assert "function hasSettledAssistant(" in src
    assert "!lifecycleApi().isCompleted(article)" in src
    assert "Boolean(exportableAssistantText(article))" in src


def test_export_collects_only_settled_with_pending_user() -> None:
    src = _source()
    collect_start = src.index("function collectConversation(")
    collect_end = src.index("function exportFilename(", collect_start)
    collect = src[collect_start:collect_end]
    # Must use pendingUser to avoid leaking failed trailing user
    assert "let pendingUser = null;" in collect
    assert 'pendingUser = text ? { label: "나", text } : null;' in collect
    assert "if (!text) {" in collect
    assert "pendingUser = null;" in collect
    assert "if (pendingUser) {" in collect
    assert "entries.push(pendingUser);" in collect
    assert 'entries.push({ label: "Padiem Chat", text });' in collect
    # Must use exportableAssistantText, not raw visiblePlainText
    assert "exportableAssistantText(article)" in collect


def test_export_state_is_fail_closed_on_incomplete() -> None:
    src = _source()
    state_start = src.index("function updateExportState(")
    state_end = src.index("function downloadConversation(", state_start)
    state = src[state_start:state_end]
    assert "const settled = hasSettledAssistant();" in state
    assert "const usable = settled && !hasIncompleteAssistant();" in state
    assert "exportButton.hidden = !settled;" in state
    assert "exportButton.disabled = !usable;" in state


def test_export_download_is_fail_closed_and_requires_completed() -> None:
    src = _source()
    download_start = src.index("function downloadConversation(")
    download_end = src.index('exportButton.addEventListener("click", downloadConversation);', download_start)
    download = src[download_start:download_end]
    assert "if (hasIncompleteAssistant() || exportButton.disabled) return;" in download
    assert 'entries.some((entry) => entry.label === "Padiem Chat")' in download
    assert "new Blob([formatConversation(entries)]" in download


def test_export_excludes_typed_error_via_skip_selector() -> None:
    src = _source()
    assert '".typing"' in src
    assert '".error-box"' in src
    assert "SKIP_SELECTOR" in src
    # Ensure after terminal completion, final answer is used (collect via exportableAssistantText after isCompleted)
    assert "visiblePlainText" in src
