"""Regression for #4318: first-use Claw must expose explicit model choice.

No network, provider, account mutation, product model defaults or shared
Chat/Mode1 composer JS changes. This exercises the shipped CSS in Chromium.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_claw_general_verified_model_is_visible_without_default() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(
                """<!doctype html>
                <html lang="ko" data-theme="padiem-glass"><body>
                  <div class="app-shell" data-state="claw">
                    <section class="claw-workspace" data-view="general"></section>
                    <section class="composer-wrap">
                      <form id="composerForm">
                        <label class="claw-model-choice" for="clawVerifiedModelSelect">
                          <span>파디엠플러스 모델 선택</span>
                          <select id="clawVerifiedModelSelect">
                            <option value="">모델을 직접 선택하세요</option>
                            <option value="google/gemini-3.5-flash-lite">gemini-3.5-flash-lite</option>
                          </select>
                        </label>
                        <details class="claw-model-advanced"><summary>고급 입력</summary>
                          <input id="clawModelIdInput" /></details>
                        <button id="ownerModelPreviewOpen">모델 현황</button>
                        <textarea id="messageInput"></textarea>
                        <button id="sendButton" type="submit">↑</button>
                      </form>
                    </section>
                  </div>
                </body></html>"""
            )
            page.add_style_tag(path=str(STATIC / "claw-workspace.css"))
            page.add_style_tag(path=str(STATIC / "claw-focus-layout.css"))

            # Must be visible on FIRST Claw screen before sending a model call.
            chooser = page.locator("#clawVerifiedModelSelect")
            assert chooser.is_visible()
            assert chooser.input_value() == ""  # no automatic model selection
            assert not page.locator(".claw-model-advanced").is_visible()
            assert not page.locator("#ownerModelPreviewOpen").is_visible()
            assert page.locator("#messageInput").is_visible()

            # The existing server-listed choice is explicit, not an implicit
            # tier promotion or provider fallback. A user may choose it.
            chooser.select_option("google/gemini-3.5-flash-lite")
            assert chooser.input_value() == "google/gemini-3.5-flash-lite"

            # Chat must not inherit Claw's model picker.
            page.locator(".app-shell").evaluate(
                "(element) => element.dataset.state = 'home'"
            )
            assert not chooser.is_visible()
            assert page.locator("#messageInput").is_visible()

            # Claw manual non-general mode preserves its advanced controls.
            page.locator(".app-shell").evaluate(
                "(element) => element.dataset.state = 'claw'"
            )
            page.locator(".claw-workspace").evaluate(
                "(element) => element.dataset.view = 'manual'"
            )
            assert chooser.is_visible()
            assert page.locator(".claw-model-advanced").is_visible()
        finally:
            browser.close()
