"""Exact browser gate for B01 Personal Edition V7 Collectible Glass / Issue #613 continuity."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright
from scripts.build_static_preview import main as build_static_preview

BASE_DIR = Path(__file__).resolve().parent.parent
DIST = BASE_DIR / "dist-preview"
VIEWPORTS = (("desktop", 1440, 1100), ("mobile", 390, 844))
SCREENS = (
    ("entry", "/preview/intro/", ".v3-intro"),
    ("guide", "/guide/", ".v3-guide"),
    ("access", "/preview/participant/access/", ".v3-workflow"),
    ("library", "/preview/participant/published/", ".v3-library"),
    ("write", "/preview/participant/input/", ".v3-write"),
    ("read", "/preview/participant/editions/modal-preview-edition/", ".v3-read"),
    ("transformation", "/preview/participant/transformation/", ".transformation-page"),
    ("history", "/preview/participant/history/", ".v3-history"),
    ("feedback", "/preview/participant/editions/modal-preview-edition/feedback/", ".v3-feedback"),
    ("thanks", "/preview/participant/editions/modal-preview-edition/feedback/thanks/", ".v3-thanks"),
    ("adaptation", "/preview/participant/editions/modal-preview-edition/adaptation/", ".v3-adaptation"),
)


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def system_browser() -> str | None:
    for candidate in (
        os.getenv("CHROME_PATH"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def launch_browser(pw):
    kwargs: dict[str, object] = {"headless": True, "args": ["--no-sandbox"]}
    executable = system_browser()
    if executable:
        kwargs["executable_path"] = executable
    return pw.chromium.launch(**kwargs)


@pytest.fixture(scope="module")
def server() -> tuple[str, Path]:
    build_static_preview()
    handler = partial(Quiet, directory=str(DIST))
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    host, port = http.server_address
    evidence = Path(os.getenv("RUNNER_TEMP", tempfile.gettempdir())) / "b01-v7-collectible-glass"
    (evidence / "screenshots").mkdir(parents=True, exist_ok=True)
    try:
        yield f"http://{host}:{port}", evidence
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)


def test_v7_static_authority_and_admin_boundary() -> None:
    base = (BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    required = (
        "/static/ui-v6-living-index.css?v=b1-living-index-v6-20260814",
        "/static/ui-v6-living-index-completion.css?v=b1-living-index-v6-completion-20260814",
        "/static/ui-v7-collectible-glass.css?v=b1-collectible-glass-v7-20260814",
    )
    for marker in required:
        assert marker in base
    assert base.index("ui-v7-collectible-glass.css") > base.index("ui-v6-living-index-completion.css")
    assert 'b1-personal-edition-v7-collectible-glass' in base
    assert 'data-design-system="b1-collectible-glass-v7"' in base
    assert 'data-owner-ui-approved="false"' in base
    # V6 art-direction marker is intentionally retained as the compatibility layer selector.
    assert 'b1-living-index-v6' in base
    # Operator workspace intentionally keeps the existing visual authority.
    assert 'b1-personal-edition-v3-454' in base
    assert 'b1-image-led-v5' in base


def test_v7_exact_desktop_mobile_surfaces(server: tuple[str, Path]) -> None:
    base, evidence = server
    shots: list[dict[str, object]] = []
    failures: list[str] = []

    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            for viewport_name, width, height in VIEWPORTS:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce",
                )
                page = context.new_page()
                external: list[str] = []
                page_errors: list[str] = []
                console_errors: list[str] = []
                http_errors: list[str] = []

                page.on(
                    "request",
                    lambda request: external.append(request.url)
                    if not request.url.startswith(base)
                    and not request.url.startswith(("data:", "blob:"))
                    else None,
                )
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )

                def on_response(response):
                    path = urlparse(response.url).path
                    if response.url.startswith(base) and response.status >= 400 and path != "/favicon.ico":
                        http_errors.append(f"{response.status} {path}")

                page.on("response", on_response)

                for screen_name, path, marker in SCREENS:
                    response = page.goto(base + path, wait_until="networkidle", timeout=15000)
                    assert response is not None and response.status == 200, (screen_name, path)
                    assert page.locator(marker).count() > 0, (screen_name, marker)
                    assert page.locator("body").get_attribute("data-art-direction") == "b1-living-index-v6"
                    assert page.locator("body").get_attribute("data-design-system") == "b1-collectible-glass-v7"
                    assert page.locator("body").get_attribute("data-ui-version") == "b1-personal-edition-v7-collectible-glass"
                    assert page.locator("body").get_attribute("data-owner-ui-approved") == "false"

                    metrics = page.evaluate(
                        """() => ({
                          sw: document.documentElement.scrollWidth,
                          cw: document.documentElement.clientWidth,
                          broken: Array.from(document.images)
                            .filter(i => i.complete && i.naturalWidth === 0)
                            .map(i => i.src),
                          rm: matchMedia('(prefers-reduced-motion: reduce)').matches
                        })"""
                    )
                    assert metrics["sw"] <= metrics["cw"] + 1, (screen_name, viewport_name, metrics)
                    assert metrics["broken"] == [], (screen_name, metrics["broken"])
                    assert metrics["rm"] is True

                    page.evaluate("document.activeElement && document.activeElement.blur()")
                    page.keyboard.press("Tab")
                    focus_visible = page.evaluate(
                        """() => {
                          const el = document.activeElement;
                          if (!el || el === document.body) return false;
                          const s = getComputedStyle(el);
                          return (parseFloat(s.outlineWidth || '0') > 0 && s.outlineStyle !== 'none') ||
                                 (s.boxShadow && s.boxShadow !== 'none');
                        }"""
                    )
                    assert focus_visible, (screen_name, viewport_name, "focus-visible")

                    if screen_name == "entry":
                        assert page.locator(".v7-photo-cluster img").count() == 3
                        assert page.locator(".v3-hero-title").evaluate(
                            "el => getComputedStyle(el).color"
                        ) == "rgb(17, 20, 24)"
                        glass = page.locator(".v3-edition-object").evaluate(
                            "el => ({bg:getComputedStyle(el).backgroundImage, bf:getComputedStyle(el).backdropFilter})"
                        )
                        assert "linear-gradient" in glass["bg"]
                        assert glass["bf"] != "none"
                    elif screen_name == "library":
                        background = page.locator(".v3-library-object-zone").evaluate(
                            "el => getComputedStyle(el).backgroundImage"
                        )
                        assert "library-edition-stack.webp" in background
                    elif screen_name == "write":
                        background = page.locator(".v3-write-margin").evaluate(
                            "el => getComputedStyle(el, '::after').backgroundImage"
                        )
                        assert "human-proof-review.webp" in background
                    elif screen_name == "read":
                        background = page.locator(".v3-read-cover-zone").evaluate(
                            "el => getComputedStyle(el).backgroundImage"
                        )
                        assert "edition-opening.webp" in background
                        assert page.locator(".v3-read-title h1").evaluate(
                            "el => getComputedStyle(el).color"
                        ) == "rgb(17, 20, 24)"
                    elif screen_name == "history":
                        background = page.locator(".v3-history-head").evaluate(
                            "el => getComputedStyle(el, '::after').backgroundImage"
                        )
                        assert "edition-library-history.webp" in background
                    elif screen_name == "thanks":
                        mark = page.locator(".v3-thanks-mark").evaluate(
                            "el => ({bg:getComputedStyle(el).backgroundImage, color:getComputedStyle(el).color})"
                        )
                        assert "linear-gradient" in mark["bg"]
                        assert mark["color"] == "rgb(34, 39, 40)"
                    elif screen_name == "adaptation":
                        background = page.locator(".v3-adapt-head").evaluate(
                            "el => getComputedStyle(el).backgroundImage"
                        )
                        assert "linear-gradient" in background

                    shot = evidence / "screenshots" / f"{screen_name}-{viewport_name}.png"
                    page.screenshot(path=str(shot), full_page=False)
                    shots.append(
                        {
                            "screen": screen_name,
                            "viewport": viewport_name,
                            "width": width,
                            "height": height,
                            "sha256": sha256(shot),
                        }
                    )

                failures.extend(external)
                failures.extend(page_errors)
                failures.extend(console_errors)
                failures.extend(http_errors)
                context.close()
        finally:
            browser.close()

    assert failures == [], failures
    assert len(shots) == 22
    assert len({str(item["sha256"]) for item in shots}) == 22
    (evidence / "manifest.json").write_text(
        json.dumps(
            {
                "issue": 613,
                "direction": "V7 — Collectible Glass",
                "status": "pass",
                "screenshots": shots,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_v7_admin_surface_remains_operator_v5(server: tuple[str, Path]) -> None:
    base, _ = server
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            response = page.goto(base + "/admin/", wait_until="networkidle", timeout=15000)
            assert response is not None and response.status == 200
            assert page.locator("body").get_attribute("data-art-direction") == "b1-image-led-v5"
            assert page.locator("body").get_attribute("data-ui-version") == "b1-personal-edition-v3-454"
            assert page.locator("body").get_attribute("data-design-system") is None
        finally:
            browser.close()
