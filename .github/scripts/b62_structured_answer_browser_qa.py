from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_STRUCTURED_QA_BASE_URL", "http://127.0.0.1:8774")
OUT_DIR = Path(os.environ.get("B62_STRUCTURED_QA_OUT_DIR", ".tmp/b62-structured-answer-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

RAW_ANSWER = """# 주말 계획
요약 문단입니다.

- 산책
- 독서

1. 준비
2. 실행

> 무리하지 않습니다.

```javascript
window.__PADIEM_CODE_EXECUTED = true;
console.log(\"<safe>\");
```

| 항목 | 설명 | 값 |
| --- | --- | --- |
| A | 쉼,표 | 10 |
| B | \"따옴표\" | 20 |

<img src=x onerror=\"window.__PADIEM_HTML_EXECUTED = true\">
""".rstrip()

EXPECTED_CSV = (
    '\ufeff"항목","설명","값"\r\n'
    '"A","쉼,표","10"\r\n'
    '"B","""따옴표""","20"'
)


async def _assert_no_horizontal_overflow(page: Page, label: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {label}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


async def _run_view(page: Page, *, name: str, width: int, height: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    chat_posts: list[dict[str, Any]] = []

    async def route_handler(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)

        if parsed.path == "/health":
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "runtime": "mock",
                        "live_enabled": False,
                        "web_tools_ready": False,
                        "deep_research_ready": False,
                    }
                ),
            )
            return

        if request.method == "POST" and parsed.path == "/api/chat/stream":
            payload: Any = None
            if request.post_data:
                try:
                    payload = json.loads(request.post_data)
                except json.JSONDecodeError:
                    payload = request.post_data
            chat_posts.append({"path": parsed.path, "payload": payload})
            body = "".join(
                [
                    f"event: delta\ndata: {json.dumps({'delta': RAW_ANSWER}, ensure_ascii=False)}\n\n",
                    f"event: done\ndata: {json.dumps({'done': True}, ensure_ascii=False)}\n\n",
                ]
            )
            await route.fulfill(
                status=200,
                headers={
                    "Content-Type": "text/event-stream; charset=utf-8",
                    "Cache-Control": "no-cache, no-store",
                },
                body=body,
            )
            return

        await route.continue_()

    await page.route("**/*", route_handler)
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await _assert_no_horizontal_overflow(page, f"{name}-empty")

    await page.locator("#messageInput").fill("주말 계획을 표와 코드 예시로 정리해줘")
    await page.locator("#sendButton").click()

    article = page.locator("#messageList .assistant-message").last
    await article.wait_for(state="visible", timeout=10_000)
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-message:last-of-type')?.dataset.richResponse === 'true'",
        timeout=10_000,
    )

    if len(chat_posts) != 1 or chat_posts[0]["path"] != "/api/chat/stream":
        raise AssertionError(f"ordinary structured answer must use one streaming request: {chat_posts!r}")
    payload = chat_posts[0]["payload"]
    if isinstance(payload, dict) and any(key in payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser payload contains routing identity: {payload!r}")

    raw_source = article.locator(".assistant-content > p.rich-response-source")
    if await raw_source.count() != 1:
        raise AssertionError("exactly one canonical raw source paragraph must remain")
    raw_text = await raw_source.text_content()
    if raw_text != RAW_ANSWER:
        raise AssertionError(f"raw answer changed during rich rendering:\nEXPECTED={RAW_ANSWER!r}\nACTUAL={raw_text!r}")
    if not await raw_source.is_hidden():
        raise AssertionError("canonical raw paragraph should be hidden after successful rich render")

    rich = article.locator(".rich-response")
    await rich.wait_for(state="visible")
    heading = (await rich.locator(".rich-response-heading").first.inner_text()).strip()
    if heading != "주말 계획":
        raise AssertionError(f"heading mismatch: {heading!r}")

    unordered = [text.strip() for text in await rich.locator("ul.rich-response-list li").all_inner_texts()]
    ordered = [text.strip() for text in await rich.locator("ol.rich-response-list li").all_inner_texts()]
    if unordered != ["산책", "독서"]:
        raise AssertionError(f"unordered list mismatch: {unordered!r}")
    if ordered != ["준비", "실행"]:
        raise AssertionError(f"ordered list mismatch: {ordered!r}")

    quote = (await rich.locator("blockquote.rich-response-quote").inner_text()).strip()
    if quote != "무리하지 않습니다.":
        raise AssertionError(f"blockquote mismatch: {quote!r}")

    code = rich.locator(".rich-code-block code")
    code_text = await code.text_content()
    expected_code = 'window.__PADIEM_CODE_EXECUTED = true;\nconsole.log("<safe>");'
    if code_text != expected_code:
        raise AssertionError(f"code block mismatch: {code_text!r}")
    if await page.evaluate("Boolean(window.__PADIEM_CODE_EXECUTED)"):
        raise AssertionError("rendered code executed")

    # Headless Chromium normally supports the existing local clipboard/fallback path.
    code_copy = rich.locator(".rich-code-copy")
    await code_copy.click()
    await page.wait_for_timeout(50)
    copy_label = (await code_copy.inner_text()).strip()
    if copy_label not in {"복사됨", "복사 실패", "복사"}:
        raise AssertionError(f"unexpected code-copy state: {copy_label!r}")

    table = rich.locator(".rich-table-block table")
    if await table.count() != 1:
        raise AssertionError("expected one semantic table")
    headers = [text.strip() for text in await table.locator("thead th").all_inner_texts()]
    rows = [
        [cell.strip() for cell in await table.locator("tbody tr").nth(index).locator("td").all_inner_texts()]
        for index in range(await table.locator("tbody tr").count())
    ]
    if headers != ["항목", "설명", "값"]:
        raise AssertionError(f"table headers mismatch: {headers!r}")
    if rows != [["A", "쉼,표", "10"], ["B", '"따옴표"', "20"]]:
        raise AssertionError(f"table rows mismatch: {rows!r}")

    csv_download_button = rich.locator(".rich-table-download")
    async with page.expect_download(timeout=5_000) as csv_info:
        await csv_download_button.click()
    csv_download = await csv_info.value
    csv_path = OUT_DIR / f"{name}-table.csv"
    await csv_download.save_as(str(csv_path))
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    expected_without_bom = EXPECTED_CSV.lstrip("\ufeff")
    if csv_text != expected_without_bom:
        raise AssertionError(f"CSV content mismatch: {csv_text!r}")

    # outputs.js must still operate from the exact hidden raw paragraph.
    answer_download = article.locator(".answer-download")
    await answer_download.wait_for(state="visible", timeout=5_000)
    async with page.expect_download(timeout=5_000) as txt_info:
        await answer_download.click()
    txt_download = await txt_info.value
    txt_path = OUT_DIR / f"{name}-answer.txt"
    await txt_download.save_as(str(txt_path))
    txt_text = txt_path.read_text(encoding="utf-8")
    if txt_text != RAW_ANSWER:
        raise AssertionError("whole-answer TXT download did not preserve exact canonical raw answer")

    # The HTML-like payload must remain literal text; it must not become executable DOM.
    if await rich.locator("img").count() != 0 or await rich.locator("script").count() != 0:
        raise AssertionError("HTML-like answer text was interpreted as DOM")
    if await page.evaluate("Boolean(window.__PADIEM_HTML_EXECUTED)"):
        raise AssertionError("HTML-like answer payload executed")
    body_text = await article.inner_text()
    if '<img src=x onerror="window.__PADIEM_HTML_EXECUTED = true">' not in body_text:
        raise AssertionError("HTML-like payload must remain visible as literal text")

    forbidden = ("Gemini", "Agnes", "Poolside", "OpenRouter", "b14/auto", "selected_provider", "selected_model")
    leaked = [value for value in forbidden if value in body_text]
    if leaked:
        raise AssertionError(f"provider/model jargon leaked into answer UI: {leaked!r}")

    table_scroller = rich.locator(".rich-table-scroll")
    if await table_scroller.count() != 1:
        raise AssertionError("wide-table scroller wrapper is missing")
    overflow_x = await table_scroller.evaluate("el => getComputedStyle(el).overflowX")
    if overflow_x not in {"auto", "scroll"}:
        raise AssertionError(f"table scroller must own horizontal overflow, got {overflow_x!r}")

    await _assert_no_horizontal_overflow(page, f"{name}-structured")
    await page.screenshot(path=str(OUT_DIR / f"{name}-structured.png"), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "chat_post_path": chat_posts[0]["path"],
        "raw_answer_exact": True,
        "heading": heading,
        "unordered_items": unordered,
        "ordered_items": ordered,
        "blockquote": quote,
        "code_execution": False,
        "code_copy_state": copy_label,
        "table_headers": headers,
        "table_rows": rows,
        "csv_file": csv_path.name,
        "csv_exact": True,
        "txt_file": txt_path.name,
        "txt_raw_exact": True,
        "html_passthrough": False,
        "provider_model_leak": [],
        "horizontal_overflow": False,
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "fixture_only": True,
        "real_provider_calls_expected": 0,
        "views": {},
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            desktop = await browser.new_page(accept_downloads=True)
            report["views"]["desktop"] = await _run_view(
                desktop, name="desktop", width=1440, height=1000
            )
            await desktop.close()

            mobile = await browser.new_page(accept_downloads=True)
            report["views"]["mobile"] = await _run_view(
                mobile, name="mobile", width=390, height=844
            )
            await mobile.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
