from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RICH_PATH = ROOT / "static" / "rich-response.js"
APP_PATH = ROOT / "static" / "app.js"
SEARCH_PATH = ROOT / "static" / "search-sources.js"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_composer_disabled_state_is_the_single_rich_enhancement_gate() -> None:
    rich = _source(RICH_PATH)
    start = rich.index("  function canEnhanceAnswers() {")
    end = rich.index("  function enhanceAssistantMessage(", start)
    helper = rich[start:end]

    result = json.loads(
        _run_node(
            "let messageInput = { disabled: true };\n"
            + helper
            + "\nconst during = canEnhanceAnswers();\n"
            + "messageInput.disabled = false;\n"
            + "const after = canEnhanceAnswers();\n"
            + "console.log(JSON.stringify({ during, after }));"
        )
    )

    assert result == {"during": False, "after": True}


def test_first_middle_and_final_stream_mutations_cannot_enhance_while_in_flight() -> None:
    rich = _source(RICH_PATH)

    assistant_start = rich.index("  function enhanceAssistantMessage(")
    assistant_end = rich.index("  function enhanceAllAnswers(", assistant_start)
    assistant = rich[assistant_start:assistant_end]
    assert assistant.index("if (!canEnhanceAnswers()) return;") < assistant.index("article.dataset.richResponse")
    assert assistant.index("if (!canEnhanceAnswers()) return;") < assistant.index("buildRichResponse(")

    all_start = rich.index("  function enhanceAllAnswers(")
    all_end = rich.index("  const messageObserver", all_start)
    enhance_all = rich[all_start:all_end]
    assert "if (!canEnhanceAnswers()) return;" in enhance_all
    assert enhance_all.index("if (!canEnhanceAnswers()) return;") < enhance_all.index("querySelectorAll")

    # The streaming writer mutates the same paragraph on every delta while the
    # existing request lifecycle keeps the composer disabled.
    app = _source(APP_PATH)
    assert "input.disabled = inFlight;" in app
    assert "paragraph.textContent = answer;" in app
    assert "inFlight = true;" in app
    assert "inFlight = false;" in app


def test_disabled_attribute_release_runs_enhancement_once_against_final_dom() -> None:
    rich = _source(RICH_PATH)

    assert 'const messageInput = document.getElementById("messageInput");' in rich
    assert 'lifecycleObserver.observe(messageInput, { attributes: true, attributeFilter: ["disabled"] });' in rich

    lifecycle_start = rich.index("  const lifecycleObserver = new MutationObserver(")
    lifecycle_end = rich.index("  lifecycleObserver.observe", lifecycle_start)
    callback = rich[lifecycle_start:lifecycle_end]
    assert "if (canEnhanceAnswers()) enhanceAllAnswers();" in callback

    app = _source(APP_PATH)
    finally_start = app.index("    } finally {", app.index("  async function requestAnswer("))
    finally_end = app.index("  async function submitPrompt(", finally_start)
    request_finally = app[finally_start:finally_end]
    assert request_finally.index("inFlight = false;") < request_finally.index("updateComposer();")


def test_stream_error_remains_raw_and_is_not_rich_enhanced_after_unlock() -> None:
    rich = _source(RICH_PATH)
    assert 'content.querySelector(".error-box")' in rich

    app = _source(APP_PATH)
    stream_start = app.index("  async function requestStreamingAnswer(")
    stream_end = app.index("  async function requestAnswer(", stream_start)
    stream = app[stream_start:stream_end]
    assert "renderStreamError(article, message" in stream
    assert "renderStreamError(article, error instanceof Error" in stream


def test_completed_or_stored_answers_still_enhance_when_composer_is_enabled() -> None:
    rich = _source(RICH_PATH)
    assert "enhanceAllAnswers();\n})();" in rich
    assert 'messageList.querySelectorAll(".assistant-message").forEach(enhanceAssistantMessage);' in rich

    app = _source(APP_PATH)
    assert 'paragraph.textContent = result.answer;' in app
    assert 'paragraph.textContent = text;' in app


def test_slice21_tool_transport_contract_is_not_reimplemented_here() -> None:
    rich = _source(RICH_PATH)
    search = _source(SEARCH_PATH)

    assert "fetch(" not in rich
    assert "PadiemChatToolBridge" not in rich
    assert 'payload.tool = toolId' in search
    assert '"/api/chat/stream"' in search
    assert '"/api/chat"' in search
