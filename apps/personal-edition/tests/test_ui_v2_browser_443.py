"""Real-browser evidence gate for B1 Personal Edition UI V2 / Issue #443.

The test intentionally uses a system Chrome/Chromium executable instead of
Playwright-downloaded browser binaries so the normal Personal Edition CI job can
run it without changing production/runtime dependencies or CI workflow files.

It builds the existing deterministic static preview, serves it on localhost,
then verifies the exact #443 viewport matrix, participant/operator click flows,
responsive overflow, local assets, keyboard focus and reduced-motion behavior.
Screenshots and a JSON manifest are written outside the repository under the
runner temp directory. GitHub Actions also receives a concise job summary.
"""

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
from playwright.sync_api import Page, sync_playwright

from scripts.build_static_preview import main as build_static_preview

BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "dist-preview"

VIEWPORTS = (
    ("desktop", 1440, 1100),
    ("tablet", 768, 1024),
    ("mobile", 390, 844),
)

SCREENS = (
    ("intro", "/preview/intro/"),
    ("participant-published", "/preview/participant/published/"),
    ("edition-read", "/preview/participant/editions/modal-preview-edition/"),
    (
        "feedback-adaptation",
        "/preview/participant/editions/modal-preview-edition/adaptation/",
    ),
    ("operator-queue", "/admin/"),
    ("operator-participant-context", "/admin/participants/modal-preview-user/"),
    (
        "operator-content-review",
        "/admin/review/modal-preview-edition/content/",
    ),
    (
        "operator-publish-decision",
        "/admin/review/modal-preview-edition/publish/",
    ),
)

PARTICIPANT_FLOW = (
    ("/preview/intro/", "a.btn-primary", "/preview/participant/access/"),
    (
        "/preview/participant/access/",
        "a[href='/preview/participant/empty/']",
        "/preview/participant/empty/",
    ),
    (
        "/preview/participant/empty/",
        "a[href$='/input']",
        "/preview/participant/input/",
    ),
    (
        "/preview/participant/input/",
        "a[href$='/input-received/']",
        "/preview/participant/input-received/",
    ),
    (
        "/preview/participant/input-received/",
        "a[href$='/editing/']",
        "/preview/participant/editing/",
    ),
    (
        "/preview/participant/editing/",
        "a[href$='/published/']",
        "/preview/participant/published/",
    ),
    (
        "/preview/participant/published/",
        "a.latest-edition",
        "/preview/participant/editions/modal-preview-edition/",
    ),
    (
        "/preview/participant/editions/modal-preview-edition/",
        "a[href$='/feedback'], a[href$='/feedback/']",
        "/preview/participant/editions/modal-preview-edition/feedback/",
    ),
    (
        "/preview/participant/editions/modal-preview-edition/feedback/",
        "a[href$='/feedback/thanks'], a[href$='/feedback/thanks/']",
        "/preview/participant/editions/modal-preview-edition/feedback/thanks/",
    ),
    (
        "/preview/participant/editions/modal-preview-edition/feedback/thanks/",
        "a[href$='/adaptation']",
        "/preview/participant/editions/modal-preview-edition/adaptation/",
    ),
    (
        "/preview/participant/editions/modal-preview-edition/adaptation/",
        "a[href$='/history']",
        "/preview/participant/history/",
    ),
)

OPERATOR_FLOW = (
    ("/admin/access/", "a[href='/admin/']", "/admin/"),
    (
        "/admin/",
        "a[href='/admin/participants/modal-preview-user/']",
        "/admin/participants/modal-preview-user/",
    ),
    (
        "/admin/participants/modal-preview-user/",
        "a[href='/admin/review/modal-preview-edition/']",
        "/admin/review/modal-preview-edition/",
    ),
    (
        "/admin/review/modal-preview-edition/",
        "a[href='/admin/review/modal-preview-edition/evidence/']",
        "/admin/review/modal-preview-edition/evidence/",
    ),
    (
        "/admin/review/modal-preview-edition/evidence/",
        "a[href='/admin/review/modal-preview-edition/content/']",
        "/admin/review/modal-preview-edition/content/",
    ),
    (
        "/admin/review/modal-preview-edition/content/",
        "a[href='/admin/review/modal-preview-edition/publish/']",
        "/admin/review/modal-preview-edition/publish/",
    ),
    (
        "/admin/review/modal-preview-edition/publish/",
        "a[href='/admin/participants/modal-preview-user/feedback/']",
        "/admin/participants/modal-preview-user/feedback/",
    ),
)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def _browser_executable() -> str:
    candidates = (
        os.getenv("CHROME_PATH"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise AssertionError(
        "Issue #443 browser evidence requires a system Chrome/Chromium executable"
    )


def _pr_head_sha() -> str:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file():
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
            sha = event.get("pull_request", {}).get("head", {}).get("sha")
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


def _evidence_dir() -> Path:
    root = Path(os.getenv("RUNNER_TEMP", tempfile.gettempdir()))
    path = root / f"personal-edition-ui-v2-443-{_pr_head_sha()}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "screenshots").mkdir(exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm_path(url: str) -> str:
    path = urlparse(url).path or "/"
    return path if path.endswith("/") else path + "/"


def _assert_screen_basics(page: Page, base_url: str, path: str) -> dict[str, object]:
    console_errors: list[str] = []
    page_errors: list[str] = []
    external_requests: list[str] = []

    def on_console(msg: object) -> None:
        if getattr(msg, "type", None) == "error":
            console_errors.append(str(getattr(msg, "text", msg)))

    def on_page_error(exc: object) -> None:
        page_errors.append(str(exc))

    def on_request(request: object) -> None:
        url = str(getattr(request, "url", ""))
        if url and not url.startswith(base_url) and not url.startswith(("data:", "blob:")):
            external_requests.append(url)

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("request", on_request)
    response = page.goto(base_url + path, wait_until="networkidle", timeout=15_000)
    assert response is not None and response.status == 200, path
    page.wait_for_timeout(120)

    metrics = page.evaluate(
        """() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
            reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
            brokenImages: Array.from(document.images)
                .filter(img => img.complete && img.naturalWidth === 0)
                .map(img => img.getAttribute('src')),
        })"""
    )
    assert metrics["scrollWidth"] <= metrics["clientWidth"], (
        path,
        metrics["scrollWidth"],
        metrics["clientWidth"],
    )
    assert metrics["reducedMotion"] is True, path
    assert metrics["brokenImages"] == [], (path, metrics["brokenImages"])
    assert console_errors == [], (path, console_errors)
    assert page_errors == [], (path, page_errors)
    assert external_requests == [], (path, external_requests)

    # Use keyboard modality so :focus-visible is evaluated rather than plain :focus.
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Tab")
    focus = page.evaluate(
        """() => {
            const el = document.activeElement;
            if (!el || el === document.body) return {tag: null, visible: false};
            const cs = getComputedStyle(el);
            const outline = parseFloat(cs.outlineWidth || '0') > 0 && cs.outlineStyle !== 'none';
            const shadow = cs.boxShadow && cs.boxShadow !== 'none';
            return {tag: el.tagName, visible: Boolean(outline || shadow)};
        }"""
    )
    assert focus["tag"] is not None, (path, focus)
    assert focus["visible"] is True, (path, focus)
    return metrics


@pytest.fixture(scope="module")
def preview_server() -> tuple[str, Path]:
    build_static_preview()
    assert DIST_DIR.is_dir()

    handler = partial(_QuietHandler, directory=str(DIST_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    evidence = _evidence_dir()
    try:
        yield base_url, evidence
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_issue_443_exact_viewport_matrix_in_real_chromium(
    preview_server: tuple[str, Path],
) -> None:
    base_url, evidence = preview_server
    executable = _browser_executable()
    screenshots: list[dict[str, object]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=executable,
            args=["--no-sandbox"],
        )
        try:
            for viewport_name, width, height in VIEWPORTS:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce",
                )
                page = context.new_page()
                for screen_name, path in SCREENS:
                    _assert_screen_basics(page, base_url, path)
                    shot = evidence / "screenshots" / f"{screen_name}-{viewport_name}.png"
                    page.screenshot(path=str(shot), full_page=False)
                    screenshots.append(
                        {
                            "screen": screen_name,
                            "viewport": viewport_name,
                            "width": width,
                            "height": height,
                            "file": str(shot),
                            "sha256": _sha256(shot),
                        }
                    )
                context.close()
        finally:
            browser.close()

    assert len(screenshots) == 24
    assert len({item["sha256"] for item in screenshots}) == 24

    manifest = {
        "issue": 443,
        "prHeadSha": _pr_head_sha(),
        "status": "pass",
        "screenshots": screenshots,
        "count": len(screenshots),
    }
    manifest_path = evidence / "screenshot-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8") as handle:
            handle.write("\n## B1 Personal Edition UI V2 — Issue #443 browser evidence\n\n")
            handle.write(f"- PR head: `{manifest['prHeadSha']}`\n")
            handle.write(f"- Browser: `{executable}`\n")
            handle.write("- Viewports: `1440×1100`, `768×1024`, `390×844`\n")
            handle.write(f"- Screenshots captured: **{len(screenshots)} / 24**\n")
            handle.write(f"- Evidence directory: `{evidence}`\n")
            handle.write("- Result: **PASS**\n")


def _run_flow(page: Page, base_url: str, steps: tuple[tuple[str, str, str], ...]) -> None:
    for start, selector, expected in steps:
        response = page.goto(base_url + start, wait_until="networkidle", timeout=15_000)
        assert response is not None and response.status == 200, start
        page.click(selector, timeout=8_000)
        page.wait_for_load_state("networkidle", timeout=10_000)
        assert _norm_path(page.url) == expected, (start, selector, page.url, expected)


def test_issue_443_real_sequential_participant_and_operator_clicks(
    preview_server: tuple[str, Path],
) -> None:
    base_url, _ = preview_server
    executable = _browser_executable()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=executable,
            args=["--no-sandbox"],
        )
        try:
            participant = browser.new_context(
                viewport={"width": 1440, "height": 1100}, reduced_motion="reduce"
            ).new_page()
            _run_flow(participant, base_url, PARTICIPANT_FLOW)
            participant.context.close()

            operator = browser.new_context(
                viewport={"width": 1440, "height": 1100}, reduced_motion="reduce"
            ).new_page()
            _run_flow(operator, base_url, OPERATOR_FLOW)
            operator.context.close()
        finally:
            browser.close()
