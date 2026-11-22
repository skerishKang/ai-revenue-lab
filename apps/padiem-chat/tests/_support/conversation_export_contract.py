"""#8060 parsed facts for the conversation-export lifecycle contract.

The raw static read stays here; the contract asserts parsed helper facts
instead of pinning source spelling.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "static" / "conversation-export.js"

LIFECYCLE_TOKENS = (
    "window.PadiemChatLifecycle", "lifecycleApi().isCompleted(article)",
    "padiem:message-lifecycle", "function exportableAssistantText(",
    "function hasIncompleteAssistant(", "function hasSettledAssistant(",
    "!lifecycleApi().isCompleted(article)", "Boolean(exportableAssistantText(article))",
    '".typing"', '".error-box"', "SKIP_SELECTOR", "visiblePlainText",
)
LEGACY_TOKENS = ("messageInput", "requestInFlight", "messageInput.disabled")
EXPORTABLE_TOKENS = (
    "lifecycleApi().isCompleted(article)", 'content.querySelector(".typing")',
    'content.querySelector(".error-box")', "visiblePlainText(content)",
)
COLLECT_TOKENS = (
    "let pendingUser = null;", 'pendingUser = text ? { label: "나", text } : null;',
    "if (!text) {", "pendingUser = null;", "if (pendingUser) {", "entries.push(pendingUser);",
    'entries.push({ label: "Padiem Chat", text });', "exportableAssistantText(article)",
)
STATE_TOKENS = (
    "const settled = hasSettledAssistant();",
    "const usable = settled && !hasIncompleteAssistant();",
    "exportButton.hidden = !settled;",
    "exportButton.disabled = !usable;",
)
DOWNLOAD_TOKENS = (
    "if (hasIncompleteAssistant() || exportButton.disabled) return;",
    'entries.some((entry) => entry.label === "Padiem Chat")',
    "new Blob([formatConversation(entries)]",
)


def _block(source: str, start: str, end: str) -> str:
    if start not in source:
        return ""
    rest = source.split(start, 1)[1]
    return rest.split(end, 1)[0] if end in rest else rest


def _present(tokens, text: str) -> tuple[str, ...]:
    return tuple(token for token in tokens if token in text)


def facts() -> dict:
    source = SOURCE.read_text(encoding="utf-8")
    exportable = _block(source, "function exportableAssistantText(", "function hasIncompleteAssistant(")
    collect = _block(source, "function collectConversation(", "function exportFilename(")
    state = _block(source, "function updateExportState(", "function downloadConversation(")
    download = _block(source, "function downloadConversation(",
                      'exportButton.addEventListener("click", downloadConversation);')
    return {
        "lifecycle_present": _present(LIFECYCLE_TOKENS, source),
        "legacy_present": _present(LEGACY_TOKENS, source),
        "exportable_present": _present(EXPORTABLE_TOKENS, exportable),
        "collect_present": _present(COLLECT_TOKENS, collect),
        "state_present": _present(STATE_TOKENS, state),
        "download_present": _present(DOWNLOAD_TOKENS, download),
    }
