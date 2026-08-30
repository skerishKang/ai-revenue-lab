from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_CONVERSATION_EXPORT_QA_BASE_URL", "http://127.0.0.1:8777")
OUT_DIR = Path(os.environ.get("B62_CONVERSATION_EXPORT_QA_OUT_DIR", ".tmp/b62-conversation-export-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

SUCCESS_PROMPT = "스트리밍 중에는 대화 내보내기를 잠가줘"
SUCCESS_PARTS = (
    "첫 번째 답변 조각입니다. ",
    "두 번째 답변 조각이 이어지고, ",
    "세 번째 조각으로 답변이 완성됩니다.",
)
SUCCESS_ANSWER = "".join(SUCCESS_PARTS)
ERROR_PROMPT = "부분 답변 뒤 오류를 재현해줘"
ERROR_PARTIAL = "오류 전에 잠깐 보이는 부분 답변입니다."
ERROR_MESSAGE = "의도된 대화 내보내기 스트림 오류"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _stream_init_script() -> str:
    script = r"""
(() => {
  const successPrompt = __SUCCESS_PROMPT__;
  const successParts = __SUCCESS_PARTS__;
  const errorPrompt = __ERROR_PROMPT__;
  const errorPartial = __ERROR_PARTIAL__;
  const errorMessage = __ERROR_MESSAGE__;
  const originalFetch = window.fetch.bind(window);
  const streamPosts = [];
  Object.defineProperty(window, "__qaConversationExportStreamPosts", { value: streamPosts });
  Object.defineProperty(window, "__qaConversationExportStreamPhase", { value: "idle", writable: true });

  function frame(eventName, payload) {
    return `event: ${eventName}\ndata: ${JSON.stringify(payload)}\n\n`;
  }

  function delayedResponse(frames, phases) {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        let index = 0;
        const emit = () => {
          window.__qaConversationExportStreamPhase = phases[index];
          controller.enqueue(encoder.encode(frames[index]));
          index += 1;
          if (index >= frames.length) {
            controller.close();
            return;
          }
          window.setTimeout(emit, 650);
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

    const payload = typeof init.body === "string" ? JSON.parse(init.body) : {};
    streamPosts.push(payload);
    const messages = Array.isArray(payload.messages) ? payload.messages : [];
    const last = messages.length ? messages[messages.length - 1] : null;
    const prompt = last && last.role === "user" ? last.content : "";

    if (prompt === successPrompt) {
      const frames = successParts.map((part) => frame("delta", { delta: part }));
      frames.push(frame("done", { done: true, conversation_id: "chat_export_stream_success" }));
      return delayedResponse(
        frames,
        ["success-delta-1", "success-delta-2", "success-delta-3", "success-done"],
      );
    }

    if (prompt === errorPrompt) {
      return delayedResponse(
        [
          frame("delta", { delta: errorPartial }),
          frame("error", { error: { code: "intentional_export_stream_error", message: errorMessage } }),
        ],
        ["error-delta", "error-terminal"],
      );
    }

    throw new Error(`unexpected stream prompt: ${String(prompt)}`);
  };
})();
"""
    for marker, value in {
        "__SUCCESS_PROMPT__": _json(SUCCESS_PROMPT),
        "__SUCCESS_PARTS__": _json(list(SUCCESS_PARTS)),
        "__ERROR_PROMPT__": _json(ERROR_PROMPT),
        "__ERROR_PARTIAL__": _json(ERROR_PARTIAL),
        "__ERROR_MESSAGE__": _json(ERROR_MESSAGE),
    }.items():
        script = script.replace(marker, value)
    return script


async def _assert_export_unusable(page: Page, stage: str) -> None:
    button = page.locator("#conversationExportButton")
    await button.wait_for(state="attached", timeout=5_000)
    visible = await button.is_visible()
    disabled = await button.is_disabled()
    if visible and not disabled:
        raise AssertionError(f"conversation export was usable during {stage}")


async def _assert_export_usable(page: Page, stage: str) -> None:
    button = page.locator("#conversationExportButton")
    await button.wait_for(state="attached", timeout=5_000)
    if not await button.is_visible() or await button.is_disabled():
        raise AssertionError(f"conversation export was not usable during {stage}")


async def _download_export(page: Page) -> str:
    async with page.expect_download(timeout=5_000) as pending:
        await page.locator("#conversationExportButton").click()
    download = await pending.value
    path = await download.path()
    if path is None:
        raise AssertionError("browser did not materialize conversation export")
    return Path(path).read_text(encoding="utf-8")


async def main() -> None:
    report_path = OUT_DIR / "stream-lifecycle-report.json"
    report: dict[str, object] = {
        "status": "RUNNING",
        "real_provider_calls": 0,
        "production_mutation": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(locale="ko-KR", accept_downloads=True)
                page = await context.new_page()
                await page.add_init_script(_stream_init_script())
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

                await _assert_export_unusable(page, "empty conversation")

                await page.locator("#messageInput").fill(SUCCESS_PROMPT)
                await page.locator("#sendButton").click()
                await page.wait_for_function(
                    "() => window.__qaConversationExportStreamPhase === 'success-delta-1'",
                    timeout=5_000,
                )
                await _assert_export_unusable(page, "first visible delta")
                if not await page.locator("#messageInput").is_disabled():
                    raise AssertionError("composer was not locked during first delta")
                partial = (await page.locator("#messageList .assistant-message:last-of-type .assistant-content p").inner_text()).strip()
                if partial != SUCCESS_PARTS[0].strip():
                    raise AssertionError(f"unexpected first partial answer: {partial!r}")
                await page.screenshot(path=str(OUT_DIR / "stream-export-partial.png"), full_page=True)

                await page.wait_for_function(
                    "() => window.__qaConversationExportStreamPhase === 'success-delta-2'",
                    timeout=5_000,
                )
                await _assert_export_unusable(page, "second visible delta")

                await page.wait_for_function(
                    "() => window.__qaConversationExportStreamPhase === 'success-done'",
                    timeout=5_000,
                )
                await page.wait_for_function(
                    "expected => document.querySelector('#messageList .assistant-message:last-of-type .assistant-content p')?.textContent.trim() === expected && document.getElementById('messageInput')?.disabled === false",
                    arg=SUCCESS_ANSWER,
                    timeout=5_000,
                )
                await _assert_export_usable(page, "settled successful response")
                await page.screenshot(path=str(OUT_DIR / "stream-export-final.png"), full_page=True)

                exported = await _download_export(page)
                if f"나:\n{SUCCESS_PROMPT}" not in exported:
                    raise AssertionError("success prompt missing from exported conversation")
                expected_assistant = f"Padiem Chat:\n{SUCCESS_ANSWER}"
                if expected_assistant not in exported:
                    raise AssertionError(f"export did not contain exact terminal answer: {exported!r}")
                for part in SUCCESS_PARTS:
                    if part.strip() not in exported:
                        raise AssertionError(f"export lost a final answer segment: {part!r}")

                # Keep the successful exchange in the same conversation, then force the
                # next request to terminate with an SSE error. Export must stay locked
                # during the failed request and, once settled, must export only completed
                # exchanges -- never the dangling failed user prompt or partial answer.
                await page.locator("#messageInput").fill(ERROR_PROMPT)
                await page.locator("#sendButton").click()
                await page.wait_for_function(
                    "() => window.__qaConversationExportStreamPhase === 'error-delta'",
                    timeout=5_000,
                )
                await _assert_export_unusable(page, "partial response before terminal error")
                error_partial = (await page.locator("#messageList .assistant-message:last-of-type .assistant-content p").inner_text()).strip()
                if error_partial != ERROR_PARTIAL:
                    raise AssertionError(f"unexpected error partial: {error_partial!r}")

                await page.locator("#messageList .assistant-message:last-of-type .error-box").wait_for(
                    state="visible",
                    timeout=5_000,
                )
                await page.wait_for_function(
                    "() => document.getElementById('messageInput')?.disabled === false",
                    timeout=5_000,
                )
                await _assert_export_usable(page, "settled error after prior successful exchange")
                await page.screenshot(path=str(OUT_DIR / "stream-export-error.png"), full_page=True)

                exported_after_error = await _download_export(page)
                if f"나:\n{SUCCESS_PROMPT}" not in exported_after_error or expected_assistant not in exported_after_error:
                    raise AssertionError("prior completed exchange disappeared after later stream error")
                for forbidden in (ERROR_PROMPT, ERROR_PARTIAL, ERROR_MESSAGE):
                    if forbidden in exported_after_error:
                        raise AssertionError(f"failed trailing exchange leaked into export: {forbidden!r}")

                stream_posts = await page.evaluate("window.__qaConversationExportStreamPosts || []")
                if len(stream_posts) != 2:
                    raise AssertionError(f"expected exactly two synthetic stream posts, got {len(stream_posts)}")

                report.update(
                    {
                        "status": "PASS",
                        "stream_posts": len(stream_posts),
                        "success_delta_count": len(SUCCESS_PARTS),
                        "export_usable_during_first_delta": False,
                        "export_usable_during_second_delta": False,
                        "terminal_export_exact_final": True,
                        "partial_error_export_usable_during_request": False,
                        "prior_success_export_usable_after_later_error": True,
                        "failed_trailing_exchange_excluded": True,
                    }
                )
                await context.close()
            finally:
                await browser.close()
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
