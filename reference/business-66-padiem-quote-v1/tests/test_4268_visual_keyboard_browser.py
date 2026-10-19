"""B66 #4268: emulate visual-only mobile keyboard shrink without customer writes.

This is a browser proxy for keyboard viewport behavior, NOT physical device proof.
"""
from __future__ import annotations

import http.server
from pathlib import Path
import socketserver
import threading

from playwright.sync_api import sync_playwright

B66 = Path(__file__).resolve().parents[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(B66), **kwargs)

    def log_message(self, *_args):
        pass


class Server(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    with Server(("127.0.0.1", 0), QuietHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        address = f"http://127.0.0.1:{server.server_address[1]}/index.html"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height, visual_height in [
                    (320, 640, 365),
                    (360, 740, 440),
                    (390, 844, 470),
                    (390, 844, 380),
                ]:
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        is_mobile=True,
                        has_touch=True,
                        device_scale_factor=1,
                    )
                    context.route(
                        "**/*",
                        lambda route: route.continue_()
                        if route.request.method.upper() in {"GET", "HEAD"}
                        else route.abort(),
                    )
                    page = context.new_page()
                    failures: list[str] = []
                    page.on("pageerror", lambda error: failures.append(str(error)))
                    page.goto(address, wait_until="domcontentloaded")
                    page.wait_for_function("Boolean(window.B66ShellLayout)")
                    composer = page.locator("#easyComposer")
                    composer.focus()

                    def visual(height_override: int, scale: float = 1.0) -> dict:
                        return page.evaluate(
                            """({heightOverride, scale}) => {
                              const viewport = window.visualViewport;
                              Object.defineProperty(viewport, "height", {
                                configurable: true, get: () => heightOverride
                              });
                              Object.defineProperty(viewport, "scale", {
                                configurable: true, get: () => scale
                              });
                              viewport.dispatchEvent(new Event("resize"));
                              const rect = document.querySelector(".easy-composer")
                                .getBoundingClientRect();
                              return {
                                bottom: rect.bottom,
                                visibleBottom: viewport.offsetTop + viewport.height,
                                css: getComputedStyle(document.querySelector(".easy-view")).height,
                                override: document.documentElement.style
                                  .getPropertyValue("--b66-visual-height"),
                              };
                            }""",
                            {"heightOverride": height_override, "scale": scale},
                        )

                    state = visual(visual_height)
                    assert state["override"] == f"{visual_height}px", (width, state)
                    assert state["bottom"] <= state["visibleBottom"] + 1, (width, state)

                    zoom = visual(visual_height, 1.5)
                    assert zoom["override"] == "", (width, "pinch zoom guard", zoom)
                    reopened = visual(height, 1.0)
                    assert reopened["override"] == "", (width, "keyboard close", reopened)
                    composer.blur()
                    page.wait_for_timeout(32)
                    blurred = visual(visual_height)
                    assert blurred["override"] == "", (width, "unfocused", blurred)
                    assert not failures, (width, failures)
                    assert not page.evaluate(
                        "document.documentElement.scrollWidth > innerWidth + 2"
                    ), (width, "horizontal overflow")
                    print(
                        f"B66_VISUAL_KEYBOARD_PROXY_PASS={width}x{height} "
                        f"visual={visual_height} composer_bottom={state['bottom']:.1f}",
                        flush=True,
                    )
                    context.close()
            finally:
                browser.close()
        server.shutdown()

    print("B66_VISUAL_KEYBOARD_PROXY=PASS; PHYSICAL_DEVICE=NOT_TESTED", flush=True)


if __name__ == "__main__":
    main()
