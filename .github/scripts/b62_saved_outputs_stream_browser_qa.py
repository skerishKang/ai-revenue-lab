from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_OUTPUTS_QA_BASE_URL", "http://127.0.0.1:8771")
OUT_DIR = Path(os.environ.get("B62_OUTPUTS_QA_OUT_DIR", ".tmp/b62-saved-outputs-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_NAME = "스트리밍 저장 회귀 사용자"
QUESTION = "스트리밍 답변을 세 부분으로 보여줘"
ANSWER_PARTS = (
    "첫 번째 조각입니다. ",
    "두 번째 조각까지 이어지고, ",
    "세 번째 조각으로 최종 답변이 완성됩니다.",
)
ANSWER = "".join(ANSWER_PARTS)
ERROR_QUESTION = "부분 답변 뒤 오류를 재현해줘"
ERROR_PARTIAL = "이 문장은 오류 전에 잠깐 보이는 부분 답변입니다."
ERROR_MESSAGE = "의도된 스트리밍 회귀 테스트 오류"
OUTPUT_ID = "out_stream_lifecycle_000000000000001"
FORBIDDEN_KEYS = frozenset({"model", "provider", "route", "business14"})


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _reply_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=_json(payload),
        headers={"Cache-Control": "no-store"},
    )


def _request_json(route: Route) -> dict[str, Any]:
    raw = route.request.post_data
    value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise AssertionError(f"expected object payload, got {value!r}")
    return value


def _stream_init_script() -> str:
    template = r"""
(() => {
  const successQuestion = __SUCCESS_QUESTION__;
  const successParts = __SUCCESS_PARTS__;
  const errorQuestion = __ERROR_QUESTION__;
  const errorPartial = __ERROR_PARTIAL__;
  const errorMessage = __ERROR_MESSAGE__;
  const originalFetch = window.fetch.bind(window);
  const streamPosts = [];
  Object.defineProperty(window, "__qaStreamPosts", { value: streamPosts });
  Object.defineProperty(window, "__qaStreamPhase", { value: "idle", writable: true });

  function frame(eventName, payload) {
    return `event: ${eventName}\ndata: ${JSON.stringify(payload)}\n\n`;
  }

  function delayedResponse(frames, phases) {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        let index = 0;
        const emit = () => {
          window.__qaStreamPhase = phases[index];
          controller.enqueue(encoder.encode(frames[index]));
          index += 1;
          if (index >= frames.length) {
            controller.close();
            return;
          }
          window.setTimeout(emit, 700);
        };
        window.setTimeout(emit, 20);
      },
    });
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  }

  window.fetch = async (input, init = {}) => {
    const rawUrl = typeof input === "string" ? input : input.url;
    const url = new URL(rawUrl, window.location.href);
    if (url.pathname !== "/api/chat/stream") return originalFetch(input, init);

    const requestBody = typeof init.body === "string" ? JSON.parse(init.body) : {};
    streamPosts.push(requestBody);
    const messages = Array.isArray(requestBody.messages) ? requestBody.messages : [];
    const lastMessage = messages.length ? messages[messages.length - 1] : null;
    const question = lastMessage && lastMessage.role === "user" ? lastMessage.content : "";

    if (question === successQuestion) {
      const frames = successParts.map((part) => frame("delta", { delta: part }));
      frames.push(frame("done", { done: true, conversation_id: "chat_stream_lifecycle_success" }));
      return delayedResponse(
        frames,
        ["success-delta-1", "success-delta-2", "success-delta-3", "success-done"],
      );
    }

    if (question === errorQuestion) {
      return delayedResponse(
        [
          frame("delta", { delta: errorPartial }),
          frame("error", { error: { code: "intentional_stream_error", message: errorMessage } }),
        ],
        ["error-delta", "error-terminal"],
      );
    }

    throw new Error(`unexpected stream question: ${String(question)}`);
  };
})();
"""
    replacements = {
        "__SUCCESS_QUESTION__": _json(QUESTION),
        "__SUCCESS_PARTS__": _json(list(ANSWER_PARTS)),
        "__ERROR_QUESTION__": _json(ERROR_QUESTION),
        "__ERROR_PARTIAL__": _json(ERROR_PARTIAL),
        "__ERROR_MESSAGE__": _json(ERROR_MESSAGE),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


async def _install_api(page: Page, output_posts: list[dict[str, Any]]) -> None:
    async def auth(route: Route) -> None:
        await _reply_json(
            route,
            {
                "ready": True,
                "authenticated": True,
                "history_ready": True,
                "project_files_ready": False,
                "user": {
                    "id": "usr_stream_lifecycle_fixture",
                    "email": "stream-lifecycle@example.test",
                    "name": USER_NAME,
                    "picture": "",
                },
            },
        )

    async def empty_list(route: Route) -> None:
        key = "projects" if route.request.url.endswith("/api/projects") else "conversations"
        await _reply_json(route, {key: []})

    async def outputs(route: Route) -> None:
        if route.request.method == "GET":
            await _reply_json(route, {"outputs": []})
            return
        if route.request.method != "POST":
            await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        body = _request_json(route)
        output_posts.append(body)
        await _reply_json(
            route,
            {
                "output": {
                    "id": OUTPUT_ID,
                    "title": body.get("title"),
                    "content": body.get("content"),
                    "conversation_id": None,
                    "project_id": None,
                    "created_at": "2026-08-30T00:00:00Z",
                    "updated_at": "2026-08-30T00:00:00Z",
                }
            },
            status=201,
        )

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/projects", empty_list)
    await page.route("**/api/conversations", empty_list)
    await page.route("**/api/outputs", outputs)


async def _install_browser_fixtures(page: Page) -> None:
    await page.add_init_script(
        """
        (() => {
          const writes = [];
          Object.defineProperty(window, "__qaClipboardWrites", { value: writes });
          Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: { writeText: async (text) => { writes.push(String(text)); } },
          });
        })();
        """
    )
    await page.add_init_script(_stream_init_script())

    async def css(route: Route) -> None:
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* qa stub */")

    async def font(route: Route) -> None:
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _download_text(page: Page, selector: str, expected: str) -> str:
    async with page.expect_download(timeout=5_000) as pending:
        await page.locator(selector).click()
    download = await pending.value
    path = await download.path()
    if path is None:
        raise AssertionError("download did not expose a local file path")
    content = Path(path).read_text(encoding="utf-8")
    if content != expected:
        raise AssertionError(f"download captured stale/partial answer: {content!r}")
    return download.suggested_filename


async def _latest_assistant(page: Page):
    return page.locator("#messageList .assistant-message").last


async def main() -> None:
    report_path = OUT_DIR / "stream-lifecycle-report.json"
    report: dict[str, Any] = {"status": "RUNNING", "real_provider_calls": 0, "production_mutation": False}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    output_posts: list[dict[str, Any]] = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
                await _install_browser_fixtures(page)
                await _install_api(page, output_posts)
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

                await page.wait_for_function(
                    "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected && !document.getElementById('outputsNavButton')?.hidden",
                    arg=USER_NAME,
                    timeout=5_000,
                )

                await page.locator("#messageInput").fill(QUESTION)
                await page.locator("#sendButton").click()
                await page.wait_for_function("() => window.__qaStreamPhase === 'success-delta-1'", timeout=5_000)
                success_article = await _latest_assistant(page)
                await success_article.locator(".assistant-content p").wait_for(state="visible", timeout=5_000)
                first_visible = (await success_article.locator(".assistant-content p").inner_text()).strip()
                if first_visible != ANSWER_PARTS[0].strip():
                    raise AssertionError(f"first delta was not isolated: {first_visible!r}")
                if await success_article.locator(".answer-actions").count() != 0:
                    raise AssertionError("answer actions appeared before terminal stream completion")
                if not await page.locator("#messageInput").is_disabled():
                    raise AssertionError("composer unlocked before terminal stream completion")
                await page.screenshot(path=str(OUT_DIR / "stream-lifecycle-partial.png"), full_page=True)

                await page.wait_for_function("() => window.__qaStreamPhase === 'success-done'", timeout=5_000)
                await page.wait_for_function(
                    "expected => document.querySelector('#messageList .assistant-message:last-of-type .assistant-content p')?.textContent.trim() === expected",
                    arg=ANSWER,
                    timeout=5_000,
                )
                for selector in (".answer-copy", ".answer-download", ".answer-save"):
                    await success_article.locator(selector).wait_for(state="visible", timeout=5_000)
                await page.wait_for_function("() => document.getElementById('messageInput')?.disabled === false", timeout=5_000)
                await page.screenshot(path=str(OUT_DIR / "stream-lifecycle-final.png"), full_page=True)

                await success_article.locator(".answer-copy").click()
                await page.wait_for_function("expected => window.__qaClipboardWrites?.at(-1) === expected", arg=ANSWER)
                answer_download = await _download_text(page, "#messageList .assistant-message:last-of-type .answer-download", ANSWER)

                await success_article.locator(".answer-save").click()
                await page.wait_for_function(
                    "() => document.querySelector('#messageList .assistant-message:last-of-type .answer-save')?.dataset.saved === 'true'",
                    timeout=5_000,
                )
                if output_posts != [{"title": ANSWER[:100], "content": ANSWER}]:
                    raise AssertionError(f"save POST did not use exact terminal answer/title: {output_posts!r}")

                await page.locator("#newChatButton").click()
                await page.locator("#messageInput").fill(ERROR_QUESTION)
                await page.locator("#sendButton").click()
                await page.wait_for_function("() => window.__qaStreamPhase === 'error-delta'", timeout=5_000)
                error_article = await _latest_assistant(page)
                error_partial = (await error_article.locator(".assistant-content p").inner_text()).strip()
                if error_partial != ERROR_PARTIAL:
                    raise AssertionError(f"unexpected error partial answer: {error_partial!r}")
                if await error_article.locator(".answer-actions").count() != 0:
                    raise AssertionError("answer actions appeared on partial stream before error")

                await error_article.locator(".error-box").wait_for(state="visible", timeout=5_000)
                await page.wait_for_function("() => document.getElementById('messageInput')?.disabled === false", timeout=5_000)
                if await error_article.locator(".answer-actions").count() != 0:
                    raise AssertionError("partial stream error retained successful answer actions")
                await page.screenshot(path=str(OUT_DIR / "stream-lifecycle-error.png"), full_page=True)

                stream_posts = await page.evaluate("window.__qaStreamPosts || []")
                if len(stream_posts) != 2:
                    raise AssertionError(f"expected two browser stream POSTs, saw {len(stream_posts)}")
                expected_questions = [QUESTION, ERROR_QUESTION]
                for index, body in enumerate(stream_posts):
                    if any(key in body for key in FORBIDDEN_KEYS):
                        raise AssertionError(f"browser selected routing internals: {body!r}")
                    if body.get("messages", [])[-1:] != [{"role": "user", "content": expected_questions[index]}]:
                        raise AssertionError(f"unexpected chat payload: {body!r}")

                report.update(
                    {
                        "status": "PASS",
                        "stream_posts": len(stream_posts),
                        "success_delta_count": len(ANSWER_PARTS),
                        "pre_terminal_actions": 0,
                        "copy_exact_final": True,
                        "download_exact_final": True,
                        "save_exact_final": True,
                        "partial_error_actions": 0,
                        "download_filename": answer_download,
                    }
                )
                await page.close()
            finally:
                await browser.close()
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
