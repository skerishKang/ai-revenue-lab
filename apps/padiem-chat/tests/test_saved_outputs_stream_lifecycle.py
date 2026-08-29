from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_PATH = ROOT / "static" / "outputs.js"
APP_PATH = ROOT / "static" / "app.js"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_answer_actions_wait_until_request_lifecycle_releases() -> None:
    outputs = _source(OUTPUTS_PATH)
    app = _source(APP_PATH)

    assert 'const messageInput = document.getElementById("messageInput");' in outputs
    assert "function canEnhanceAnswers()" in outputs
    assert "return messageInput.disabled !== true;" in outputs

    enhance_start = outputs.index("  function enhanceAssistantMessage(")
    enhance_end = outputs.index("  function enhanceAllAnswers(", enhance_start)
    enhance = outputs[enhance_start:enhance_end]
    assert enhance.index("if (!canEnhanceAnswers()) return;") < enhance.index("const text = answerText(article);")

    assert 'lifecycleObserver.observe(messageInput, { attributes: true, attributeFilter: ["disabled"] });' in outputs
    assert "if (canEnhanceAnswers()) enhanceAllAnswers();" in outputs

    request_start = app.index("  async function requestAnswer(")
    request_end = app.index("  async function submitPrompt(", request_start)
    request_source = app[request_start:request_end]
    assert "inFlight = true;" in request_source
    finally_start = request_source.index("    } finally {")
    request_finally = request_source[finally_start:]
    assert request_finally.index("inFlight = false;") < request_finally.index("updateComposer();")
    assert "input.disabled = inFlight;" in app


def test_stream_final_text_is_set_before_answer_actions_unlock() -> None:
    app = _source(APP_PATH)
    outputs = _source(OUTPUTS_PATH)

    stream_start = app.index("  async function requestStreamingAnswer(")
    stream_end = app.index("  async function requestAnswer(", stream_start)
    stream_source = app[stream_start:stream_end]

    assert "answer += data.delta;" in stream_source
    assert "paragraph.textContent = answer;" in stream_source
    assert "if (done) return true;" in stream_source

    completed_start = app.index("  async function requestCompletedAnswer(")
    completed_end = app.index("  function applyStreamDone(", completed_start)
    completed_source = app[completed_start:completed_end]
    assert "renderAnswer(article, data);" in completed_source

    answer_text_start = outputs.index("  function answerText(")
    answer_text_end = outputs.index("  function feedbackButton(", answer_text_start)
    answer_text_source = outputs[answer_text_start:answer_text_end]
    assert 'content.querySelector(".typing")' in answer_text_source
    assert 'content.querySelector(".error-box")' in answer_text_source


def test_answer_actions_capture_only_terminal_visible_answer() -> None:
    outputs = _source(OUTPUTS_PATH)

    enhance_start = outputs.index("  function enhanceAssistantMessage(")
    enhance_end = outputs.index("  function enhanceAllAnswers(", enhance_start)
    enhance = outputs[enhance_start:enhance_end]

    gate = enhance.index("if (!canEnhanceAnswers()) return;")
    capture = enhance.index("const text = answerText(article);")
    copy = enhance.index("copyText(text)")
    download = enhance.index("downloadText(text, titleFromText(text))")
    save = enhance.index("JSON.stringify({ title: titleFromText(text), content: text })")

    assert gate < capture < copy
    assert capture < download
    assert capture < save

    # Once terminal enhancement has happened, the action set is intentionally stable.
    assert 'article.dataset.outputActions = "true";' in enhance
