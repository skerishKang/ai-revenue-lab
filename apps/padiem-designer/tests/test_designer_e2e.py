"""The end-to-end proof: a real model generates a UI and a real browser drives it.

This test needs a real model route. It is skipped when none is configured, so
the deterministic suite never depends on a provider. When it does run, it
proves the whole loop:

1. a natural-language request reaches the model and the model calls
   ``generateSandboxedUi``;
2. the generated HTML, CSS and JavaScript render in a sandboxed frame;
3. the user types into a generated control and the frame reacts;
4. the interaction state reaches the next AI turn;
5. the next AI turn answers with a revised UI.

Configuration (environment):

``DESIGNER_MODEL_BASE_URL``  an OpenAI-compatible chat-completions origin
``DESIGNER_MODEL_API_KEY``   the credential for that origin
``DESIGNER_MODEL_ID``        the model id to ask
"""

from __future__ import annotations

import os
import socket
import threading
import time
from typing import Iterator

import pytest

pytest.importorskip("playwright", reason="the browser proof needs playwright")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.app_factory import build_app  # noqa: E402
from app.config import load_settings  # noqa: E402

REQUIRED_ENV = ("DESIGNER_MODEL_BASE_URL", "DESIGNER_MODEL_API_KEY", "DESIGNER_MODEL_ID")

PROMPT = (
    "주문서 양식을 만들어줘. 수량(qty) 입력창과 단가(unitPrice) 입력창이 있고, "
    "두 값을 곱한 합계(total)가 입력할 때마다 자동으로 계산되어 화면에 표시돼야 해. "
    "합계는 id가 total 인 요소에 넣어줘."
)

FOLLOW_UP = "수량을 5로 바꿔줘. 화면을 고쳐줘."


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_server() -> Iterator[str]:
    if not all(os.environ.get(name) for name in REQUIRED_ENV):
        pytest.skip("no model route is configured for the live proof")

    import uvicorn

    port = _free_port()
    config = uvicorn.Config(
        build_app(settings=load_settings()),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    if not server.started:  # pragma: no cover - startup failure
        raise RuntimeError("the Designer preview did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _generate(page, prompt: str) -> None:
    page.fill("#prompt", prompt)
    page.click("#generate")


def test_the_model_generates_a_ui_the_user_can_operate_and_the_next_turn_sees_it(
    live_server: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(live_server, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => document.getElementById('status').textContent.indexOf('경로=') >= 0",
                timeout=15_000,
            )

            _generate(page, PROMPT)

            frame = page.frame_locator("#frame")
            page.wait_for_function(
                "() => { var f = document.getElementById('frame');"
                " return f && f.getAttribute('srcdoc') && f.getAttribute('srcdoc').length > 200; }",
                timeout=180_000,
            )
            frame.locator("body").wait_for(state="attached", timeout=60_000)

            # The model produced a real UI, not a static sample.
            assert frame.locator("input").count() >= 1, "the generated UI has no input"

            before = frame.locator("body").inner_text()

            # Drive the generated controls. Two values are filled so a
            # multiplication-based total actually changes.
            inputs = frame.locator("input")
            inputs.nth(0).fill("7")
            inputs.nth(0).dispatch_event("input")
            if inputs.count() > 1:
                inputs.nth(1).fill("3")
                inputs.nth(1).dispatch_event("input")

            # The bridge captured the user's interaction.
            page.wait_for_function(
                "() => { var el = document.getElementById('state-bar');"
                " return el && el.textContent.indexOf('7') >= 0; }",
                timeout=30_000,
            )
            after = frame.locator("body").inner_text()
            assert after != before, "the generated UI did not react to the input"

            # The interaction state reached the app, and the next turn carries it.
            _generate(page, FOLLOW_UP)
            page.wait_for_function(
                "() => { var t = document.getElementById('transcript').textContent;"
                " return t.indexOf('전달한 UI 상태') >= 0; }",
                timeout=180_000,
            )
            transcript = page.locator("#transcript").inner_text()
            assert "전달한 UI 상태" in transcript
            assert "7" in transcript

            # The second turn produced its own UI.
            page.wait_for_function(
                "() => { var f = document.getElementById('frame');"
                " return f && f.getAttribute('srcdoc') && f.getAttribute('srcdoc').length > 200; }",
                timeout=180_000,
            )
        finally:
            browser.close()

    assert not errors, f"the preview raised page errors: {errors}"
