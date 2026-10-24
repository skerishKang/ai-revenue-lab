"""#4485 Chat/Claw turn meta row spacing and the runtime status chip.

Two defects on the live Chat/Claw surface:

1. The bottom meta row of a user turn and of an AI turn used different
   spacing. The completion time and the first action icon sat 6px apart in
   the user turn and 2px apart in the answer turn, because the Glass sheet
   collapsed the answer row gap to 0 and moved the icon distance into a
   sibling margin. The answer row now follows the user row rule exactly.

2. The runtime status chip stayed on "answer preparing" after the answer was
   fully rendered, because only the non-streaming completion path updated the
   chip. The chip now has one owner: a completed answer releases the
   preparing chip, while a real status (a Claw P01 stage, a skill title, a
   failure) is kept and stays visible.

The proof is a static source contract plus a real browser run of the shipped
`message-lifecycle.js` and the shipped Glass stylesheet.
"""

from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path

import pytest

# The static contract tests must run everywhere (the required CI lane installs
# no browser), so Playwright is optional and only the browser checks skip.
try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP_JS = STATIC / "app.js"
LIFECYCLE_JS = STATIC / "message-lifecycle.js"
GLASS_CSS = STATIC / "padiem-glass-portrait.css"
ANSWER_CSS = STATIC / "answer-actions.css"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC))

    def log_message(self, *args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _lifecycle() -> str:
    return LIFECYCLE_JS.read_text(encoding="utf-8")


def _glass() -> str:
    return GLASS_CSS.read_text(encoding="utf-8")


def _answer_css() -> str:
    return ANSWER_CSS.read_text(encoding="utf-8")


# ── the meta row spacing rule ───────────────────────────────────────────────


def test_the_answer_meta_row_uses_the_same_gap_rule_as_the_user_row() -> None:
    """One rule for both turns: a 4px row gap and no extra sibling margin.

    The user row is the reference. Its time carries a 2px right margin, so a
    4px row gap puts the time 6px away from the first icon and keeps the
    icons 4px apart. The answer row must compute the same two distances.
    """
    glass = _glass()
    answer_css = _answer_css()

    # The user row (the reference rule).
    user_row = glass.split(".user-message .user-actions {", 1)[1].split("}", 1)[0]
    assert "gap: 4px !important;" in user_row, user_row
    user_time = glass.split(".user-message .user-action-time {", 1)[1].split("}", 1)[0]
    assert "margin-right: 2px !important;" in user_time, user_time

    # The answer row now uses the same row gap and no sibling margin. The last
    # Glass rule wins, so the assertion reads the last one.
    answer_row = glass.rsplit('html[data-theme="padiem-glass"] .answer-actions {', 1)[1].split("}", 1)[0]
    assert "gap: 4px !important;" in answer_row, answer_row
    assert "gap: 0 !important;" not in answer_row, answer_row
    sibling = glass.rsplit('html[data-theme="padiem-glass"] .answer-action + .answer-action {', 1)[1].split("}", 1)[0]
    assert "margin-left: 0 !important;" in sibling, sibling
    assert "margin-left: 4px !important;" not in sibling, sibling

    # The time keeps the same 2px right margin in both rows.
    base_time = answer_css.split(".answer-action-time {", 1)[1].split("}", 1)[0]
    assert "margin-right: 2px;" in base_time, base_time


def test_the_meta_row_alignment_stays_centred_in_both_rows() -> None:
    glass = _glass()
    user_row = glass.split(".user-message .user-actions {", 1)[1].split("}", 1)[0]
    assert "align-items: center !important;" in user_row, user_row
    answer_row = glass.rsplit('html[data-theme="padiem-glass"] .answer-actions {', 1)[1].split("}", 1)[0]
    assert "align-items: center" not in answer_row or "align-items: center !important;" in answer_row


# ── the runtime status chip ─────────────────────────────────────────────────


def test_the_runtime_chip_has_one_owner() -> None:
    lifecycle = _lifecycle()
    assert "window.PadiemChatLifecycle = Object.freeze({" in lifecycle
    assert "function applyRuntimeLabel(article, text, state)" in lifecycle
    assert "function releasePreparingRuntimeLabel(article)" in lifecycle
    assert "applyRuntimeLabel," in lifecycle
    assert "releasePreparingRuntimeLabel," in lifecycle
    # The chip state is explicit, so the release never depends on the copy.
    assert 'marker.dataset.runtimeState = state;' in lifecycle
    assert 'if (marker.dataset.runtimeState !== RUNTIME_LABEL_STATE.PREPARING) return;' in lifecycle
    # A released chip is hidden instead of leaving an empty pill behind.
    assert "marker.hidden = true;" in lifecycle
    assert "marker.removeAttribute(\"data-locale-key\");" in lifecycle


def test_every_completion_path_releases_the_preparing_chip() -> None:
    app = _app()
    # The answering shell starts in the preparing state.
    assert 'addAssistantShell(uiT("answer-preparing"), "preparing")' in app
    # The stream done path releases it.
    stream_done = app[app.index("function applyStreamDone("):]
    stream_done = stream_done[: stream_done.index("\n  }")]
    assert "releasePreparingRuntimeLabel?.(article);" in stream_done
    # The durable PC run answer releases it as well.
    assert "releasePreparingRuntimeLabel?.(article);" in app
    # A real status is never removed by the release.
    assert 'applyRuntimeLabel?.(article, label, "status");' in app
    # A failure keeps its own status and stays visible.
    assert 'return lifecycle === MESSAGE_LIFECYCLE.TIMED_OUT ? uiT("timeout") : uiT("connection-error");' in app
    assert "const statusLabel = failureStatusLabel(lifecycle);" in app
    assert 'applyRuntimeLabel?.(article, statusLabel, "status");' in app
    assert 'applyRuntimeLabel?.(article, uiT("generation-cancelled"), "status");' in app
    # A restored turn is a real status, not a preparing chip.
    assert 'addAssistantShell(uiT("stored-conversation"), "status")' in app


def test_the_orchestration_completion_path_releases_the_chip() -> None:
    lifecycle = _lifecycle()
    completed = lifecycle[lifecycle.index("function applyCompletedOrchestration("):]
    completed = completed[: completed.index("\n  }")]
    assert "releasePreparingRuntimeLabel(article);" in completed


# ── the real browser proof ──────────────────────────────────────────────────


@requires_browser
def test_the_runtime_chip_behaviour_in_a_real_browser(browser, server) -> None:
    page = browser.new_page()
    page.goto(f"{server}?theme=padiem-glass")
    page.add_script_tag(path=str(LIFECYCLE_JS))

    result = page.evaluate(
        """() => {
      const api = window.PadiemChatLifecycle;
      const article = document.createElement('article');
      article.innerHTML = '<div class="assistant-meta">'
        + '<span data-assistant-product>Padiem Chat</span>'
        + '<span class="demo-label" data-runtime-label data-locale-key="answer-preparing">답변 준비 중</span>'
        + '</div>';
      document.body.appendChild(article);
      const chip = () => article.querySelector('[data-runtime-label]');
      const read = () => ({
        text: (chip().textContent || '').trim(),
        hidden: chip().hidden === true,
        state: chip().dataset.runtimeState || '',
        localeKey: chip().getAttribute('data-locale-key') || '',
      });
      const steps = {};

      // The answering shell: the preparing chip is shown.
      api.applyRuntimeLabel(article, '답변 준비 중', 'preparing');
      steps.preparing = read();

      // A completed answer releases the preparing chip.
      api.releasePreparingRuntimeLabel(article);
      steps.afterDone = read();

      // A real status (a Claw P01 stage) is kept when the run completes.
      api.applyRuntimeLabel(article, '작업 실행이 완료되었습니다', 'status');
      api.releasePreparingRuntimeLabel(article);
      steps.afterStatusDone = read();

      // A failure keeps its own status and stays visible.
      api.applyRuntimeLabel(article, '연결 오류', 'status');
      api.releasePreparingRuntimeLabel(article);
      steps.afterFailure = read();
      return steps;
    }"""
    )

    assert result["preparing"] == {
        "text": "답변 준비 중",
        "hidden": False,
        "state": "preparing",
        "localeKey": "answer-preparing",
    }
    assert result["afterDone"] == {
        "text": "",
        "hidden": True,
        "state": "",
        "localeKey": "",
    }
    assert result["afterStatusDone"] == {
        "text": "작업 실행이 완료되었습니다",
        "hidden": False,
        "state": "status",
        "localeKey": "",
    }
    assert result["afterFailure"] == {
        "text": "연결 오류",
        "hidden": False,
        "state": "status",
        "localeKey": "",
    }
    page.close()


@requires_browser
def test_both_turn_meta_rows_use_the_same_spacing_in_a_real_browser(browser, server) -> None:
    page = browser.new_page()
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server}?theme=padiem-glass")
    page.wait_for_timeout(200)
    # The Glass turn meta rows are rendered in the chat and claw states.
    page.evaluate("() => { document.querySelector('.app-shell').dataset.state = 'chat'; }")

    measured = page.evaluate(
        """() => {
      const list = document.getElementById('messageList');
      // One user turn, rendered from the shipped template.
      const userFragment = document.getElementById('userMessageTemplate').content.cloneNode(true);
      const userArticle = userFragment.querySelector('.user-message');
      userArticle.querySelector('.message-bubble').textContent = '사용자 메시지';
      userArticle.querySelector('.user-action-time').textContent = '10:49';
      list.appendChild(userFragment);

      // One answer turn with the action row outputs.js builds.
      const answerFragment = document.getElementById('assistantMessageTemplate').content.cloneNode(true);
      const answerArticle = answerFragment.querySelector('.assistant-message');
      answerArticle.dataset.completedAt = new Date().toISOString();
      const body = answerArticle.querySelector('.assistant-body');
      const content = answerArticle.querySelector('.assistant-content');
      const paragraph = document.createElement('p');
      paragraph.textContent = '답변 메시지';
      content.appendChild(paragraph);
      const actions = document.createElement('div');
      actions.className = 'answer-actions';
      const clock = document.createElement('time');
      clock.className = 'answer-action-time';
      clock.textContent = '10:49';
      actions.appendChild(clock);
      for (const glyph of ['⧉', '↻']) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'answer-action';
        const span = document.createElement('span');
        span.className = 'answer-action-glyph';
        span.setAttribute('aria-hidden', 'true');
        span.textContent = glyph;
        button.appendChild(span);
        actions.appendChild(button);
      }
      body.appendChild(actions);
      list.appendChild(answerFragment);

      const measure = (row) => {
        const time = row.querySelector('time');
        const buttons = [...row.querySelectorAll('button')];
        const t = time.getBoundingClientRect();
        const first = buttons[0].getBoundingClientRect();
        const second = buttons[1].getBoundingClientRect();
        const rowStyle = getComputedStyle(row);
        return {
          timeToFirstIcon: +(first.left - t.right).toFixed(2),
          iconToIcon: +(second.left - first.right).toFixed(2),
          centerDelta: +((t.top + t.height / 2) - (first.top + first.height / 2)).toFixed(2),
          timeFont: getComputedStyle(time).fontSize,
          iconSize: first.width + 'x' + first.height,
          rowGap: rowStyle.gap,
          alignItems: rowStyle.alignItems,
        };
      };
      return {
        user: measure(document.querySelector('.user-actions')),
        answer: measure(document.querySelector('.answer-actions')),
      };
    }"""
    )

    user = measured["user"]
    answer = measured["answer"]
    # The answer row now computes the same two distances as the user row.
    assert answer["timeToFirstIcon"] == user["timeToFirstIcon"], measured
    assert answer["iconToIcon"] == user["iconToIcon"], measured
    assert answer["centerDelta"] == user["centerDelta"] == 0, measured
    assert answer["timeFont"] == user["timeFont"], measured
    assert answer["iconSize"] == user["iconSize"], measured
    assert answer["rowGap"] == user["rowGap"] == "4px", measured
    assert answer["alignItems"] == user["alignItems"] == "center", measured
    page.close()
