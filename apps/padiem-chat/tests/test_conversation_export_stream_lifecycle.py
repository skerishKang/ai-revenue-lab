from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = ROOT / "static" / "conversation-export.js"
APP_PATH = ROOT / "static" / "app.js"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_export_uses_composer_request_lifecycle() -> None:
    export = _source(EXPORT_PATH)
    app = _source(APP_PATH)

    assert 'const messageInput = document.getElementById("messageInput");' in export
    assert "function requestInFlight()" in export
    assert "return messageInput.disabled === true;" in export
    assert 'lifecycleObserver.observe(messageInput, { attributes: true, attributeFilter: ["disabled"] });' in export

    request_start = app.index("  async function requestAnswer(")
    request_end = app.index("  async function submitPrompt(", request_start)
    request = app[request_start:request_end]
    finally_start = request.index("    } finally {")
    request_finally = request[finally_start:]
    assert request_finally.index("inFlight = false;") < request_finally.index("updateComposer();")
    assert "input.disabled = inFlight;" in app


def test_export_skips_typing_and_error_assistant_fragments() -> None:
    export = _source(EXPORT_PATH)

    start = export.index("  function exportableAssistantText(")
    end = export.index("  function collectConversation(", start)
    helper = export[start:end]
    assert 'content.querySelector(".typing")' in helper
    assert 'content.querySelector(".error-box")' in helper
    assert "return visiblePlainText(content);" in helper

    state_start = export.index("  function updateExportState(")
    state_end = export.index("  function downloadConversation(", state_start)
    state = export[state_start:state_end]
    assert "const settled = hasSettledAssistant();" in state
    assert "const usable = settled && !requestInFlight();" in state
    assert "exportButton.disabled = !usable;" in state


def test_export_download_fails_closed_while_request_is_in_flight() -> None:
    export = _source(EXPORT_PATH)

    start = export.index("  function downloadConversation(")
    end = export.index('  exportButton.addEventListener("click", downloadConversation);', start)
    download = export[start:end]
    assert "if (requestInFlight() || exportButton.disabled) return;" in download
    assert 'entries.some((entry) => entry.label === "Padiem Chat")' in download
