"""Real Chromium gate for B2 Living Travel V2 / Issue #457."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
SITE = BASE_DIR / "site"
VIEWPORTS = (
    ("desktop", 1440, 1100),
    ("tablet", 768, 1024),
    ("mobile", 390, 844),
)
SCREENS = (
    ("owner-root", "/index.html", ".lt-hero"),
    ("preferences", "/demo/preferences.html", ".lt-pref-shell"),
    ("generation", "/demo/generation.html", ".lt-generation"),
    ("traveler-home", "/demo/traveler-home.html", ".lt-home"),
    ("edition", "/demo/edition.html", ".lt-edition"),
    ("feedback", "/demo/feedback.html", ".lt-feedback-shell"),
    ("recut", "/demo/comparison.html", ".lt-recut"),
    ("operator-review", "/operator/review.html", ".lt-op-shell"),
)


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def browser_path() -> str:
    for candidate in (
        os.getenv("CHROME_PATH"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    raise AssertionError("Issue #457 requires system Chrome/Chromium")


def head_sha() -> str:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file():
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
            sha = payload.get("pull_request", {}).get("head", {}).get("sha")
            if sha:
                return str(sha)
        except (OSError, json.JSONDecodeError):
            pass
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture(scope="module")
def server() -> tuple[str, Path]:
    handler = partial(Quiet, directory=str(SITE))
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    host, port = http.server_address
    evidence = (
        Path(os.getenv("RUNNER_TEMP", tempfile.gettempdir()))
        / f"living-travel-v2-457-{head_sha()}"
    )
    (evidence / "screenshots").mkdir(parents=True, exist_ok=True)
    try:
        yield f"http://{host}:{port}", evidence
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)


def test_issue_457_exact_viewports_and_visual_behavior(server: tuple[str, Path]) -> None:
    base, evidence = server
    shots: list[dict[str, object]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=browser_path(),
            args=["--no-sandbox"],
        )
        try:
            for viewport, width, height in VIEWPORTS:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce",
                )
                page = context.new_page()
                external: list[str] = []
                page_errors: list[str] = []
                http_errors: list[str] = []

                page.on(
                    "request",
                    lambda request: external.append(request.url)
                    if not request.url.startswith(base)
                    and not request.url.startswith(("data:", "blob:"))
                    else None,
                )
                page.on("pageerror", lambda error: page_errors.append(str(error)))

                def on_response(response: object) -> None:
                    url = response.url  # type: ignore[attr-defined]
                    status = response.status  # type: ignore[attr-defined]
                    path = urlparse(url).path
                    if url.startswith(base) and status >= 400 and path != "/favicon.ico":
                        http_errors.append(f"{status} {path}")

                page.on("response", on_response)

                for name, path, marker in SCREENS:
                    response = page.goto(
                        base + path,
                        wait_until="networkidle",
                        timeout=15000,
                    )
                    assert response is not None and response.status == 200, (name, path)
                    assert page.locator(marker).count() > 0, (name, marker)

                    metrics = page.evaluate(
                        """() => ({
                            sw: document.documentElement.scrollWidth,
                            cw: document.documentElement.clientWidth,
                            rm: matchMedia('(prefers-reduced-motion: reduce)').matches,
                            broken: Array.from(document.images)
                                .filter(i => i.complete && i.naturalWidth === 0)
                                .map(i => i.src),
                        })"""
                    )
                    assert metrics["sw"] <= metrics["cw"], (name, viewport, metrics)
                    assert metrics["rm"] is True
                    assert metrics["broken"] == [], (name, viewport, metrics["broken"])

                    # The historical QA marker may remain for deterministic tests,
                    # but it must be clipped from owner-facing visual chrome.
                    qa = page.locator(".lt-sr-only")
                    if qa.count():
                        box = qa.first.bounding_box()
                        assert box is None or (box["width"] <= 1 and box["height"] <= 1), (
                            name,
                            viewport,
                            box,
                        )

                    page.evaluate("document.activeElement && document.activeElement.blur()")
                    page.keyboard.press("Tab")
                    focus_visible = page.evaluate(
                        """() => {
                            const el = document.activeElement;
                            if (!el || el === document.body) return false;
                            const s = getComputedStyle(el);
                            return (
                                (parseFloat(s.outlineWidth || '0') > 0 && s.outlineStyle !== 'none') ||
                                (s.boxShadow && s.boxShadow !== 'none')
                            );
                        }"""
                    )
                    assert focus_visible, (name, viewport, "focus-visible")

                    if name == "owner-root":
                        assert page.locator(".demo-banner").count() == 0
                        assert page.locator(".preview-banner").count() == 0

                    shot = evidence / "screenshots" / f"{name}-{viewport}.png"
                    page.screenshot(path=str(shot), full_page=False)
                    shots.append(
                        {
                            "screen": name,
                            "viewport": viewport,
                            "width": width,
                            "height": height,
                            "sha256": sha256(shot),
                        }
                    )

                context.close()
                assert external == [], external
                assert page_errors == [], page_errors
                assert http_errors == [], http_errors
        finally:
            browser.close()

    assert len(shots) == 24
    assert len({item["sha256"] for item in shots}) == 24

    (evidence / "manifest.json").write_text(
        json.dumps(
            {
                "issue": 457,
                "head": head_sha(),
                "status": "pass",
                "screenshots": shots,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("\n## B2 Living Travel V2 — Issue #457\n\n")
            handle.write(f"- head: `{head_sha()}`\n")
            handle.write("- 3 viewports × 8 surfaces: **24/24**\n")
            handle.write("- QA chrome visually clipped: **PASS**\n")
            handle.write(
                "- overflow/assets/external requests/page errors/focus/reduced motion: **PASS**\n"
            )


def test_issue_457_has_travel_motion_and_reduced_equivalent(server: tuple[str, Path]) -> None:
    base, _ = server
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=browser_path(),
            args=["--no-sandbox"],
        )
        try:
            normal_context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                reduced_motion="no-preference",
            )
            normal = normal_context.new_page()
            normal.goto(base + "/index.html", wait_until="networkidle")
            animation = normal.locator(".lt-hero-media img").evaluate(
                "el => getComputedStyle(el).animationName"
            )
            assert animation == "ltHeroDrift"
            normal_context.close()

            reduced_context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                reduced_motion="reduce",
            )
            reduced = reduced_context.new_page()
            reduced.goto(base + "/index.html", wait_until="networkidle")
            duration = reduced.locator(".lt-hero-media img").evaluate(
                "el => getComputedStyle(el).animationDuration"
            )
            seconds = float(duration.rstrip("s")) if duration.endswith("s") else 1.0
            assert duration.endswith("ms") or seconds < 0.01, duration
            reduced_context.close()
        finally:
            browser.close()
