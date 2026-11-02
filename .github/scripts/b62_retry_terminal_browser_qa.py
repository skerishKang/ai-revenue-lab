"""Retry-path terminal contract QA (#retry-stuck-261102).

The failure card is terminal. Pressing its [다시 시도] button starts a new
turn that may itself fail, and that new turn has to end too: within seconds,
in a terminal lifecycle, with its own error card and a stopped clock. It must
not be handed to the stored PC result read-back, which polls a run handle the
retry reused from the failed turn and reports "still processing" forever when
the server keeps that run running.

Three retry shapes are driven against the same first attempt (an
``upstream_timeout`` error frame, i.e. a retryable failure card):

* ``http_refused``     - the retry POST is refused with HTTP 503.
* ``engine_stream_loss`` - the retry stream ends with the Engine stream-loss
  error frame the PC lane uses for a cut stream.
* ``stream_cut``       - the retry stream body ends before any frame.

In every shape the owner-scoped pending-result endpoint answers 200 with a run
that is still ``running``. A retry that is refused or cut must still terminate
locally; it must issue no pending-result reads at all, because the retry
inherits the failed turn's run handle and that read-back never ends the retry
turn -- it sat at "답변 준비 중" with a running clock for minutes instead.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_RETRY_TERMINAL_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get(
    "B62_RETRY_TERMINAL_QA_OUT_DIR", ".tmp/b62-retry-terminal-browser-qa",
))
OUT_DIR.mkdir(parents=True, exist_ok=True)

QUESTION = "오늘 할 일을 세 가지로 정리해줘"
FIRST_ERROR_CODE = "upstream_timeout"
REFUSED_CODE = "entitlement_unavailable"
REFUSED_COPY = "지금은 서비스를 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."
STUCK_LABEL = "답변 준비 중"
STUCK_STEP = "요청을 전달했어요."
TERMINAL_LIFECYCLES = frozenset({"failed", "timed_out", "cancelled"})
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_KEYS = frozenset({"model", "provider", "route", "business14"})
TERMINAL_DEADLINE_MS = 6_000


@dataclass
class FixtureState:
    stream_posts: list[dict[str, Any]] = field(default_factory=list)
    pending_gets: list[str] = field(default_factory=list)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {_json(payload)}\n\n"


def _request_json(route: Route) -> dict[str, Any]:
    raw = route.request.post_data
    value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise AssertionError(f"expected object payload, got {value!r}")
    return value


async def _reply_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=_json(payload),
        headers={"Cache-Control": "no-store"},
    )


async def _stub_fonts(page: Page, seen: set[str]) -> None:
    async def css(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic retry-terminal QA font stub */\n",
        )

    async def font(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


def _retry_frames(shape: str) -> tuple[int, str, str]:
    """Return status, content type, body for the retry stream POST."""
    if shape == "engine_stream_loss":
        return (200, "text/event-stream; charset=utf-8",
                _sse("error", {"error": {"code": "invalid_engine_stream", "message": "stream lost"}}))
    if shape == "stream_cut":
        return (200, "text/event-stream; charset=utf-8", "")
    raise AssertionError(f"unknown retry shape {shape!r}")


async def _install_api(page: Page, state: FixtureState, shape: str) -> None:
    async def auth(route: Route) -> None:
        await _reply_json(route, {
            "ready": False,
            "authenticated": False,
            "history_ready": False,
            "project_files_ready": False,
            "user": None,
        })

    async def orchestration_status(route: Route) -> None:
        await _reply_json(route, {"orchestration_ready": False, "authenticated": False})

    async def stream(route: Route) -> None:
        if route.request.method != "POST":
            await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        body = _request_json(route)
        state.stream_posts.append(body)
        if any(key in body for key in FORBIDDEN_KEYS):
            raise AssertionError(f"browser selected routing internals: {body!r}")
        index = len(state.stream_posts)

        if index == 1:
            if body.get("messages") != [{"role": "user", "content": QUESTION}]:
                raise AssertionError(f"unexpected first request messages: {body!r}")
            order = ("pc_run_id", "calendar_turn_id")
            if not all(isinstance(body.get(key), str) and body[key] for key in order):
                raise AssertionError(f"first submit is missing its run handle: {body!r}")
            payload = _sse("error", {"error": {"code": FIRST_ERROR_CODE, "message": "upstream timed out"}})
            await route.fulfill(
                status=200,
                content_type="text/event-stream; charset=utf-8",
                body=payload,
                headers={"Cache-Control": "no-store"},
            )
            return

        if index == 2:
            if body != state.stream_posts[0]:
                raise AssertionError(
                    "retry must replay the identical failed request context: "
                    f"first={state.stream_posts[0]!r}, retry={body!r}"
                )
            if shape == "http_refused":
                await route.fulfill(
                    status=503,
                    content_type="application/json; charset=utf-8",
                    body=_json({"ok": False, "error": {"code": REFUSED_CODE, "message": "unavailable"}}),
                    headers={"Cache-Control": "no-store"},
                )
                return
            status, content_type, payload = _retry_frames(shape)
            await route.fulfill(
                status=status,
                content_type=content_type,
                body=payload,
                headers={"Cache-Control": "no-store"},
            )
            return

        raise AssertionError(f"unexpected extra stream request #{index}: {body!r}")

    async def pending_result(route: Route) -> None:
        state.pending_gets.append(route.request.url)
        run_id = route.request.url.split("/")[-2]
        await _reply_json(route, {
            "ok": True,
            "result": {
                "run_id": run_id,
                "conversation_id": "chat_" + "a" * 32,
                "status": "running",
            },
        })

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/orchestration/status", orchestration_status)
    await page.route("**/api/chat/stream", stream)
    await page.route("**/api/claw/runs/*/pending-result", pending_result)


async def _retry_turn(page: Page) -> dict[str, Any] | None:
    return await page.evaluate(
        """() => {
            const arts = Array.from(document.querySelectorAll('#messageList .assistant-message'));
            const last = arts[arts.length - 1];
            if (!last) return null;
            const elapsed = last.querySelector('[data-turn-elapsed]');
            return {
                count: arts.length,
                lifecycle: last.dataset.lifecycle || null,
                label: (last.querySelector('[data-runtime-label]') || {}).textContent || '',
                has_error_box: Boolean(last.querySelector('.error-box')),
                has_retry: Boolean(last.querySelector('.retry-button')),
                elapsed: elapsed ? elapsed.textContent.trim() : null,
                text: last.innerText || '',
            };
        }"""
    )


async def _wait_error_card(page: Page, code: str, timeout: int = 5_000) -> None:
    await page.wait_for_function(
        "([code]) => Array.from(document.querySelectorAll('#messageList .error-code'))"
        ".some(node => node.textContent.includes(code))",
        arg=[code],
        timeout=timeout,
    )


async def _no_overflow(page: Page, stage: str) -> None:
    widths = await page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    if widths[0] > widths[1] + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {widths}")


async def _run(page: Page, *, label: str, width: int, height: int, shape: str) -> dict[str, Any]:
    state = FixtureState()
    unexpected_hosts: set[str] = set()
    stubbed_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe)
    await _stub_fonts(page, stubbed_hosts)
    await _install_api(page, state, shape)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    # The first attempt ends in the retryable failure card. Its clock is
    # stopped: this turn is terminal, and the retry starts a new turn.
    await page.locator("#messageInput").fill(QUESTION)
    await page.locator("#sendButton").click()
    await _wait_error_card(page, FIRST_ERROR_CODE)
    retry_button = page.locator("#messageList .retry-button", has_text="다시 시도")
    await retry_button.wait_for(state="visible")
    first = await _retry_turn(page)
    if first is None or first["lifecycle"] not in TERMINAL_LIFECYCLES:
        raise AssertionError(f"first failure card is not terminal: {first!r}")
    await page.screenshot(path=str(OUT_DIR / f"{label}-{shape}-first.png"), full_page=True)

    # Retry: the new turn must reach a terminal state on its own.
    await retry_button.click()
    deadline = TERMINAL_DEADLINE_MS / 1_000
    polls = int(deadline / 0.25)
    turn = None
    for _ in range(polls):
        await page.wait_for_timeout(250)
        turn = await _retry_turn(page)
        if turn and turn["has_error_box"]:
            break
    if turn is None:
        raise AssertionError("retry produced no assistant turn")
    if not turn["has_error_box"]:
        raise AssertionError(
            f"retry turn never reached a terminal error card within {TERMINAL_DEADLINE_MS}ms: {turn!r}"
        )
    if turn["lifecycle"] not in TERMINAL_LIFECYCLES:
        raise AssertionError(f"retry turn lifecycle is not terminal: {turn!r}")
    if turn["label"].strip() == STUCK_LABEL:
        raise AssertionError(f"retry turn kept the running label: {turn!r}")
    for stuck in (STUCK_LABEL, STUCK_STEP):
        if stuck in turn["text"]:
            raise AssertionError(f"retry turn kept the running wording {stuck!r}: {turn!r}")
    if not turn["has_retry"]:
        raise AssertionError(f"terminal retry turn lost its own retry action: {turn!r}")
    if shape == "http_refused":
        if REFUSED_COPY not in turn["text"]:
            raise AssertionError(f"refused retry did not keep the bounded failure copy: {turn!r}")
        if REFUSED_CODE not in turn["text"]:
            raise AssertionError(f"refused retry did not keep its reference code: {turn!r}")

    # A terminal turn stops its clock: two readings must agree.
    await page.wait_for_timeout(2_000)
    settled = await _retry_turn(page)
    if settled is None or settled["has_error_box"] is not True:
        raise AssertionError(f"retry error card disappeared: {settled!r}")
    if settled["elapsed"] != turn["elapsed"]:
        raise AssertionError(
            f"retry turn clock is still running after the terminal error: {turn['elapsed']!r} -> {settled['elapsed']!r}"
        )

    # The retry reused the failed turn's run handle, so no pending-result read
    # can ever finish this turn: the read-back must not have been started.
    if state.pending_gets:
        raise AssertionError(
            f"retry started stored-result reads for a reused run handle: {state.pending_gets!r}"
        )
    if len(state.stream_posts) != 2:
        raise AssertionError(f"expected exactly two stream posts, saw {len(state.stream_posts)}")

    await _no_overflow(page, f"{label}-{shape}-retry")
    await page.screenshot(path=str(OUT_DIR / f"{label}-{shape}-retry.png"), full_page=True)

    browser_text = await page.locator("body").inner_text()
    forbidden_public_terms = ("OpenRouter", "Gemini", "Poolside", "Agnes", "provider", "model id")
    leaked = [term for term in forbidden_public_terms if term.lower() in browser_text.lower()]
    if leaked:
        raise AssertionError(f"provider/model jargon leaked into the retry UI: {leaked}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)}")

    return {
        "retry_shape": shape,
        "stream_requests": len(state.stream_posts),
        "pending_result_gets": len(state.pending_gets),
        "retry_lifecycle": settled["lifecycle"],
        "retry_label": settled["label"],
        "retry_elapsed": settled["elapsed"],
        "stubbed_static_hosts": sorted(stubbed_hosts),
        "viewport": {"width": width, "height": height},
    }


SHAPES = ("http_refused", "engine_stream_loss", "stream_cut")


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "model_selection": "DEFERRED",
        "real_provider_calls": 0,
        "production_mutation": False,
        "views": {},
    }
    report_path = OUT_DIR / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failures: list[str] = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                    for shape in SHAPES:
                        page = await browser.new_page(viewport={"width": width, "height": height})
                        try:
                            report["views"][f"{label}-{shape}"] = await _run(
                                page, label=label, width=width, height=height, shape=shape,
                            )
                        except AssertionError as exc:
                            failures.append(f"{label}-{shape}: {exc}")
                            report["views"][f"{label}-{shape}"] = {"status": "FAIL", "error": str(exc)}
                            try:
                                await page.screenshot(
                                    path=str(OUT_DIR / f"{label}-{shape}-failure.png"), full_page=True,
                                )
                            except Exception:
                                pass
                        finally:
                            await page.close()
            finally:
                await browser.close()
        if failures:
            report["status"] = "FAIL"
            report["failures"] = failures
            raise AssertionError("; ".join(failures))
        report["status"] = "PASS"
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
