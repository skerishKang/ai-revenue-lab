from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = (
    ("light", "?theme=light"),
    ("dark", "?theme=dark"),
    ("cinematic", "?theme=cinematic"),
    ("padiem-home", "?theme=padiem-home"),
    ("padiem-glass", "?theme=padiem-glass&glass=female"),
)
VIEWPORTS = (
    ("desktop", {"width": 1440, "height": 1000}),
    ("mobile", {"width": 390, "height": 844}),
)
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
QUESTION = "제품 표면 인증을 위한 짧은 응답을 보여줘"
ANSWER = "제품 표면 인증용 결정론적 응답입니다."

REQUIRED_EXACT_HEAD_WORKFLOWS = (
    "B62 Padiem Chat CI",
    "B62 Browser Visual QA",
    "B62 Accessibility Browser QA",
    "B62 Auth History Browser QA",
    "B62 Saved Outputs Browser QA",
    "B62 Projects Browser QA",
    "B62 Project Files Browser QA",
    "B62 Document Browser QA",
    "B62 Image Browser QA",
    "B62 Error Retry Browser QA",
    "B62 Conversation Export Browser QA",
    "B62 Conversation Delete Browser QA",
    "P01 Deployment Boundary Guard",
)

CAPABILITY_MATRIX = (
    {
        "surface": "home_new_chat_composer",
        "presentation": "ACTIVE",
        "backend_active": "MOCK_OR_CONFIG_DEPENDENT",
        "production_active": "NOT_CLAIMED",
    },
    {
        "surface": "attachments",
        "presentation": "ACTIVE",
        "backend_active": "SUPPORTED_FORMAT_CONTRACT_ACTIVE",
        "production_active": "NOT_CLAIMED",
    },
    {
        "surface": "recent_conversations_projects_saved_outputs",
        "presentation": "ACTIVE_WHEN_AUTHORIZED",
        "guest_state": "HIDDEN",
        "backend_active": "AUTH_AND_STORAGE_DEPENDENT",
        "production_active": "NOT_CLAIMED",
    },
    {
        "surface": "mode_auto",
        "presentation": "ACTIVE",
        "backend_active": "AUTO_REQUEST_CONTRACT_ACTIVE",
        "production_active": "NOT_CLAIMED",
    },
    {
        "surface": "mode_fast_balanced_deep",
        "presentation": "PREVIEW_ONLY",
        "backend_active": "NO_TRUSTED_MAPPING_YET",
        "production_active": "NO",
    },
    {
        "surface": "account_session",
        "presentation": "ACTIVE_WHEN_AUTH_CONFIGURED",
        "unavailable_state": "HIDDEN",
        "backend_active": "CONTROL_PLANE_AUTH_DEPENDENT",
        "production_active": "NOT_CLAIMED",
    },
    {
        "surface": "agent_tool_approval_evidence_memory",
        "presentation": "PREVIEW_ONLY_FOR_DEMO_FIXTURES",
        "trusted_event_projection": "ACTIVE_WHEN_ENGINE_SIGNAL_PRESENT",
        "backend_active": "ENGINE_CORE_DEPENDENT",
        "production_active": "NOT_CLAIMED",
    },
)

BACKEND_DEPENDENCIES = (
    {
        "capability": "Fast / Balanced / Deep trusted execution mapping",
        "owner": "B14 / IP-ENGINE",
        "b62_action": "presentation only; do not implement provider routing",
    },
    {
        "capability": "live Agent / Tool / Approval / Evidence / Memory authority",
        "owner": "IP-ENGINE / IP-CORE",
        "b62_action": "consume normalized public-safe events only",
    },
    {
        "capability": "canonical identity / tenant / entitlement / usage / billing truth",
        "owner": "Control Plane",
        "b62_action": "present trusted account/session state only",
    },
    {
        "capability": "Production activation / routes / credentials",
        "owner": "release operations / owning platform",
        "b62_action": "no Production activation in certification",
    },
)


async def _reply_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
        headers={"Cache-Control": "no-store"},
    )


async def _stub_fonts(page: Page) -> None:
    async def css(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic product-surface certification font stub */\n",
        )

    async def font(route: Route) -> None:
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _install_api(page: Page, requests: list[dict[str, Any]]) -> None:
    async def auth(route: Route) -> None:
        await _reply_json(
            route,
            {
                "ready": True,
                "authenticated": False,
                "session_state": "guest",
                "history_ready": False,
                "project_files_ready": False,
                "user": None,
            },
        )

    async def orchestration_status(route: Route) -> None:
        await _reply_json(route, {"orchestration_ready": False, "authenticated": False})

    async def stream(route: Route) -> None:
        raw = route.request.post_data or "{}"
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise AssertionError(f"chat request must be an object: {body!r}")
        if body.get("mode") != "auto":
            raise AssertionError(f"certification request escaped provider-neutral Auto mode: {body!r}")
        if any(key in body for key in ("provider", "model", "route", "credential")):
            raise AssertionError(f"browser asserted routing authority: {body!r}")
        requests.append(body)
        await asyncio.sleep(0.2)
        payload = (
            "event: delta\n"
            f"data: {json.dumps({'delta': ANSWER}, ensure_ascii=False)}\n\n"
            "event: done\n"
            f"data: {json.dumps({'done': True, 'conversation_id': 'chat_surface_cert_0001'})}\n\n"
        )
        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=payload,
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/orchestration/status", orchestration_status)
    await page.route("**/api/chat/stream", stream)


async def _no_overflow(page: Page, label: str) -> None:
    scroll_width, inner_width = await page.evaluate(
        "() => [document.documentElement.scrollWidth, window.innerWidth]"
    )
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {label}: {scroll_width}>{inner_width}")


async def _target_height(page: Page, selector: str, label: str) -> float:
    box = await page.locator(selector).bounding_box()
    if not box or box["height"] < 40:
        raise AssertionError(f"touch target too small for {selector} at {label}: {box}")
    return round(float(box["height"]), 2)


async def _exercise_view(page: Page, *, theme: str, viewport_name: str, query: str) -> dict[str, Any]:
    label = f"{theme}-{viewport_name}"
    requests: list[dict[str, Any]] = []
    unexpected_hosts: set[str] = set()

    def observe_request(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe_request)
    await _stub_fonts(page)
    await _install_api(page, requests)
    await page.goto(f"{BASE_URL}/{query}", wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function("() => Boolean(window.PadiemChatInteractionPresentation)")
    await page.wait_for_function(
        "() => document.querySelector('.sidebar-account')?.dataset.accountState === 'guest'"
    )

    root_theme = await page.evaluate("document.documentElement.getAttribute('data-theme')")
    if root_theme != theme:
        raise AssertionError(f"theme mismatch at {label}: {root_theme!r}")

    required_visible = (
        "#newChatButton",
        ".model-pill",
        "#composerForm",
        "#messageInput",
        "#attachmentButton",
    )
    for selector in required_visible:
        if not await page.locator(selector).is_visible():
            raise AssertionError(f"required product surface hidden at {label}: {selector}")

    if viewport_name == "mobile":
        await page.locator("#mobileMenu").click()
        await page.wait_for_function("() => document.querySelector('.app-shell')?.classList.contains('sidebar-open')")
        if not await page.locator(".sidebar-account").is_visible():
            raise AssertionError(f"guest account surface not visible in mobile drawer at {label}")
        await page.locator("#mobileClose").click()
        await page.wait_for_function("() => !document.querySelector('.app-shell')?.classList.contains('sidebar-open')")
    elif not await page.locator(".sidebar-account").is_visible():
        raise AssertionError(f"guest account surface not visible on desktop at {label}")

    account_text = (await page.locator(".sidebar-account").inner_text()).strip()
    if "게스트" not in account_text or "로그인" not in account_text:
        raise AssertionError(f"guest account truth missing at {label}: {account_text!r}")

    pill = page.locator(".model-pill")
    await pill.focus()
    await page.keyboard.press("Enter")
    panel = page.locator("#modePresentationPanel")
    await panel.wait_for(state="visible")
    options = panel.locator("[data-mode-value]")
    if await options.count() != 4:
        raise AssertionError(f"mode matrix incomplete at {label}")
    if await panel.locator('[data-mode-value="auto"]').get_attribute("aria-pressed") != "true":
        raise AssertionError(f"Auto not selected at {label}")
    for mode in ("fast", "balanced", "deep"):
        if not await panel.locator(f'[data-mode-value="{mode}"]').is_disabled():
            raise AssertionError(f"{mode} must remain preview-only at {label}")
    await page.keyboard.press("Escape")
    if not await panel.is_hidden():
        raise AssertionError(f"mode panel did not close at {label}")

    await page.locator("#attachmentFileInput").set_input_files(
        {
            "name": "certification.txt",
            "mimeType": "text/plain",
            "buffer": "제품 표면 인증용 첨부".encode("utf-8"),
        }
    )
    await page.locator("#attachmentTray").wait_for(state="visible")
    await page.wait_for_function(
        "() => document.querySelector('#composerForm')?.dataset.interactionPhase === 'idle'"
    )
    await page.locator("#removeAttachment").click()
    await page.locator("#attachmentTray").wait_for(state="hidden")

    await page.locator("#messageInput").fill(QUESTION)
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "() => ['preparing', 'streaming'].includes(document.querySelector('#composerForm')?.dataset.interactionPhase)"
    )
    await page.wait_for_function(
        "answer => document.querySelector('#messageList')?.textContent.includes(answer)",
        arg=ANSWER,
        timeout=5_000,
    )
    assistant = page.locator("#messageList .assistant-message:last-child")
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-message:last-child')?.dataset.lifecycle === 'completed'"
    )
    if await assistant.get_attribute("data-terminal-actions-safe") != "true":
        raise AssertionError(f"completed response not terminal-action safe at {label}")
    await assistant.locator(".answer-actions").wait_for(state="visible")
    if len(requests) != 1:
        raise AssertionError(f"expected exactly one local mock chat request at {label}, saw {len(requests)}")
    await page.wait_for_function("() => document.activeElement?.id === 'messageInput'")

    await page.locator("#newChatButton").click()
    await page.wait_for_function("() => document.querySelector('.app-shell')?.dataset.state === 'home'")
    if not await page.locator("#messageList").is_hidden():
        raise AssertionError(f"new chat did not restore home state at {label}")

    touch_targets = {
        "new_chat": await _target_height(page, "#newChatButton", label),
        "attachment": await _target_height(page, "#attachmentButton", label),
        "send": await _target_height(page, "#sendButton", label),
    }
    await _no_overflow(page, label)
    if unexpected_hosts:
        raise AssertionError(f"unexpected external hosts at {label}: {sorted(unexpected_hosts)}")

    if label in {"light-desktop", "padiem-glass-mobile"}:
        await page.screenshot(
            path=str(OUT_DIR / f"product-surface-certification-{label}.png"),
            full_page=True,
        )

    return {
        "status": "PASS",
        "theme": theme,
        "viewport": viewport_name,
        "home_new_chat": "PASS",
        "composer": "PASS",
        "attachment_selection": "PASS",
        "streaming_terminal_actions": "PASS",
        "mode_presentation": "PASS",
        "account_session_guest": "PASS",
        "keyboard_mode_open_close": "PASS",
        "focus_recovery": "PASS",
        "horizontal_overflow": 0,
        "touch_target_heights": touch_targets,
        "local_mock_chat_requests": len(requests),
    }


async def _english_probe(browser) -> dict[str, Any]:
    page = await browser.new_page(viewport={"width": 900, "height": 720})
    requests: list[dict[str, Any]] = []
    try:
        await _stub_fonts(page)
        await _install_api(page, requests)
        await page.goto(f"{BASE_URL}/?theme=light&lang=en", wait_until="domcontentloaded", timeout=30_000)
        await page.locator("#messageInput").wait_for(state="visible")
        await page.wait_for_function("() => document.documentElement.lang === 'en'")
        await page.wait_for_function(
            "() => document.querySelector('.sidebar-account')?.dataset.accountState === 'guest'"
        )
        account_text = (await page.locator(".sidebar-account").inner_text()).strip()
        if "Guest" not in account_text or "Sign in" not in account_text:
            raise AssertionError(f"English account truth missing: {account_text!r}")
        await page.locator(".model-pill").click()
        truth = (await page.locator("[data-mode-truth]").inner_text()).strip()
        if "cannot be selected until trusted backend mappings are active" not in truth:
            raise AssertionError(f"English mode truth boundary missing: {truth!r}")
        return {
            "status": "PASS",
            "locale": "en",
            "account_session": "PASS",
            "mode_truth_boundary": "PASS",
        }
    finally:
        await page.close()


async def _reduced_motion_probe(browser) -> dict[str, Any]:
    page = await browser.new_page(viewport={"width": 900, "height": 720})
    requests: list[dict[str, Any]] = []
    try:
        await page.emulate_media(reduced_motion="reduce")
        await _stub_fonts(page)
        await _install_api(page, requests)
        await page.goto(f"{BASE_URL}/?theme=padiem-glass&glass=female", wait_until="domcontentloaded", timeout=30_000)
        reduced = await page.evaluate("window.matchMedia('(prefers-reduced-motion: reduce)').matches")
        if reduced is not True:
            raise AssertionError("reduced-motion media preference was not active")
        await _no_overflow(page, "reduced-motion")
        return {"status": "PASS", "prefers_reduced_motion": True, "horizontal_overflow": 0}
    finally:
        await page.close()


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "certification": "B62_PRODUCT_SURFACE_V2",
        "truth_boundary": {
            "UI_READY": "CERTIFIED_BY_THIS_REPORT",
            "BACKEND_ACTIVE": "NOT_IMPLIED_BY_UI_CERTIFICATION",
            "PRODUCTION_ACTIVE": "NO_CLAIM",
        },
        "capability_matrix": list(CAPABILITY_MATRIX),
        "backend_dependencies": list(BACKEND_DEPENDENCIES),
        "required_exact_head_workflows": list(REQUIRED_EXACT_HEAD_WORKFLOWS),
        "s1_s4_regression": "REQUIRES_EXACT_HEAD_PORTFOLIO_GREEN",
        "fake_live_capability_claims": 0,
        "platform_authority_duplication": 0,
        "production_mutation": False,
        "views": {},
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme, query in THEMES:
                for viewport_name, viewport in VIEWPORTS:
                    page = await browser.new_page(viewport=viewport)
                    try:
                        label = f"{theme}-{viewport_name}"
                        report["views"][label] = await _exercise_view(
                            page,
                            theme=theme,
                            viewport_name=viewport_name,
                            query=query,
                        )
                    finally:
                        await page.close()
            report["english"] = await _english_probe(browser)
            report["reduced_motion"] = await _reduced_motion_probe(browser)
        finally:
            await browser.close()

    if len(report["views"]) != 10 or not all(view.get("status") == "PASS" for view in report["views"].values()):
        raise AssertionError("expected ten certified all-theme desktop/mobile views")
    report["product_surface_desktop"] = "PASS"
    report["product_surface_mobile"] = "PASS"
    report["all_themes"] = "PASS"
    report["keyboard_accessibility"] = "PASS"
    report["horizontal_overflow"] = 0
    report["demo_ready_product_surface"] = True
    report["production_active_claim"] = "NO_UNLESS_SEPARATELY_PROVEN"
    report["status"] = "PASS"

    report_path = OUT_DIR / "product-surface-certification-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
