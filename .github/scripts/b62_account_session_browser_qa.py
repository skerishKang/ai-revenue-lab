from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_AUTH_HISTORY_QA_BASE_URL", "http://127.0.0.1:8769")
OUT_DIR = Path(os.environ.get("B62_AUTH_HISTORY_QA_OUT_DIR", ".tmp/b62-auth-history-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
VIEWPORTS = (("desktop", 1440, 1000, False), ("mobile", 390, 844, True))
USER_NAME = "브라우저 계정 사용자"


async def _fulfill_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
        headers={"Cache-Control": "no-store"},
    )


async def _install_fixtures(page: Page, state: dict[str, Any]) -> None:
    async def auth_status(route: Route) -> None:
        current = state["session"]
        if current == "unavailable":
            await _fulfill_json(route, {
                "ready": False,
                "authenticated": False,
                "history_ready": False,
                "user": None,
            })
            return
        authenticated = current == "signed_in"
        await _fulfill_json(route, {
            "ready": True,
            "authenticated": authenticated,
            "history_ready": authenticated,
            "project_files_ready": authenticated,
            "session_state": current,
            "user": ({
                "id": "usr_browser_account_fixture",
                "email": "browser@example.test",
                "name": USER_NAME,
                "picture": "",
            } if authenticated else None),
        })

    async def logout(route: Route) -> None:
        if route.request.method != "POST":
            await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, 405)
            return
        state["logout_posts"] += 1
        state["session"] = "guest"
        await _fulfill_json(route, {"ok": True})

    async def empty_projects(route: Route) -> None:
        await _fulfill_json(route, {"projects": []})

    async def empty_conversations(route: Route) -> None:
        await _fulfill_json(route, {"conversations": []})

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/auth/logout", logout)
    await page.route("**/api/projects", empty_projects)
    await page.route("**/api/conversations", empty_conversations)


async def _open_sidebar(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.locator("#sidebar").wait_for(state="visible")


async def _snapshot(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const container = document.querySelector('.sidebar-account');
          const button = document.getElementById('loginButton');
          const account = document.getElementById('accountName');
          const rect = container ? container.getBoundingClientRect() : null;
          const style = container ? getComputedStyle(container) : null;
          const publicState = window.PadiemProductCapabilities?.get?.() || null;
          return {
            href: location.href,
            auth: publicState ? publicState.auth : null,
            container: container ? {
              hidden: container.hidden,
              hiddenAttr: container.hasAttribute('hidden'),
              accountState: container.dataset.accountState || null,
              display: style?.display || null,
              visibility: style?.visibility || null,
              opacity: style?.opacity || null,
              rect: rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null,
            } : null,
            button: button ? {
              hidden: button.hidden,
              text: button.textContent?.trim() || '',
              disabled: button.disabled,
              ariaDisabled: button.getAttribute('aria-disabled'),
              title: button.title,
            } : null,
            account: account ? {
              hidden: account.hidden,
              text: account.textContent?.trim() || '',
            } : null,
          };
        }"""
    )


async def _refresh(page: Page) -> None:
    try:
        await asyncio.wait_for(
            page.evaluate("() => window.PadiemProductCapabilities.refresh()"),
            timeout=8.0,
        )
    except TimeoutError as error:
        snapshot = await _snapshot(page)
        raise AssertionError(
            "capability refresh exceeded 8s; "
            f"snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
        ) from error
    await page.wait_for_timeout(80)


async def _assert_target(page: Page, selector: str, label: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{label} has no visible target")
    if box["height"] < 44 or box["width"] < 44:
        raise AssertionError(f"{label} target below 44px: {box}")
    return {key: round(float(value), 2) for key, value in box.items()}


async def _assert_no_overflow(page: Page, label: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {label}: {scroll_width}>{inner_width}")


async def _assert_state(
    page: Page,
    state: dict[str, Any],
    expected: str,
    *,
    name: str,
    button_text: str | None,
    account_text: str | None,
) -> dict[str, Any]:
    state["session"] = expected
    print(f"ACCOUNT_SESSION_STATE_START={name}:{expected}", flush=True)
    await _refresh(page)
    container = page.locator(".sidebar-account")
    button = page.locator("#loginButton")
    account = page.locator("#accountName")
    snapshot = await _snapshot(page)

    if expected == "unavailable":
        if not await container.is_hidden() or not await button.is_hidden():
            raise AssertionError(
                f"auth unavailable must fail closed at {name}: {json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
            )
        return {"state": expected, "hidden": True, "snapshot": snapshot, "status": "PASS"}

    if await container.is_hidden():
        await page.wait_for_timeout(200)
        later = await _snapshot(page)
        raise AssertionError(
            f"account container hidden after trusted {expected} refresh at {name}; "
            f"initial={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}; "
            f"later={json.dumps(later, ensure_ascii=False, sort_keys=True)}"
        )

    await container.wait_for(state="visible")
    if await container.get_attribute("data-account-state") != expected:
        raise AssertionError(
            f"wrong account state at {name}: {await container.get_attribute('data-account-state')}; "
            f"snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
        )
    if button_text is not None and (await button.inner_text()).strip() != button_text:
        raise AssertionError(
            f"wrong account action at {name}: {(await button.inner_text()).strip()!r}; "
            f"snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
        )
    if account_text is not None and (await account.inner_text()).strip() != account_text:
        raise AssertionError(
            f"wrong account copy at {name}: {(await account.inner_text()).strip()!r}; "
            f"snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
        )
    if await button.get_attribute("aria-disabled") != "false" or await button.is_disabled():
        raise AssertionError(
            f"account action must be operable at {name}; snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
        )
    target = await _assert_target(page, "#loginButton", f"{name}-{expected}-action")
    return {"state": expected, "hidden": False, "target": target, "snapshot": snapshot, "status": "PASS"}


async def _synchronize_signed_in_action(page: Page, state: dict[str, Any], *, mobile: bool, label: str) -> None:
    state["session"] = "signed_in"
    print(f"ACCOUNT_SESSION_ACTION_SYNC_START={label}", flush=True)
    await page.reload(wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function(
        "() => document.getElementById('historySection')?.hidden === false",
        timeout=5_000,
    )
    await _open_sidebar(page, mobile)
    await _refresh(page)
    await page.wait_for_function(
        "() => document.querySelector('.sidebar-account')?.dataset.accountState === 'signed_in' && document.getElementById('loginButton')?.textContent.trim() === '로그아웃'",
        timeout=5_000,
    )
    print(f"ACCOUNT_SESSION_ACTION_SYNC_DONE={label}", flush=True)


async def _run_view(page: Page, *, theme: str, viewport_name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state: dict[str, Any] = {"session": "guest", "logout_posts": 0}
    await _install_fixtures(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    print(f"ACCOUNT_SESSION_GOTO_START={theme}-{viewport_name}", flush=True)
    await page.goto(f"{BASE_URL}/?theme={theme}", wait_until="domcontentloaded", timeout=30_000)
    print(f"ACCOUNT_SESSION_GOTO_DONE={theme}-{viewport_name}", flush=True)
    await page.locator("#messageInput").wait_for(state="visible")
    await _open_sidebar(page, mobile)

    label = f"{theme}-{viewport_name}"
    results: dict[str, Any] = {}
    results["guest"] = await _assert_state(
        page, state, "guest", name=label, button_text="로그인", account_text="게스트"
    )
    results["expired"] = await _assert_state(
        page, state, "expired", name=label, button_text="다시 로그인", account_text="세션 만료"
    )
    results["signed_in"] = await _assert_state(
        page, state, "signed_in", name=label, button_text="로그아웃", account_text=USER_NAME
    )

    await _synchronize_signed_in_action(page, state, mobile=mobile, label=label)
    print(f"ACCOUNT_SESSION_LOGOUT_START={label}", flush=True)
    await page.locator("#loginButton").focus()
    await page.locator("#loginButton").click()
    await page.wait_for_function(
        "() => document.querySelector('.sidebar-account')?.dataset.accountState === 'guest' && document.getElementById('loginButton')?.textContent.trim() === '로그인' && document.getElementById('accountName')?.hidden === false && document.getElementById('accountName')?.textContent.trim() === '게스트'",
        timeout=5_000,
    )
    print(f"ACCOUNT_SESSION_LOGOUT_DONE={label}", flush=True)
    if state["logout_posts"] != 1:
        raise AssertionError(f"logout must POST once at {label}: {state['logout_posts']}")
    results["logout"] = {"posts": state["logout_posts"], "returns_to": "guest", "status": "PASS"}

    results["unavailable"] = await _assert_state(
        page, state, "unavailable", name=label, button_text=None, account_text=None
    )
    await _assert_no_overflow(page, label)
    await page.screenshot(path=str(OUT_DIR / f"account-session-{label}.png"), full_page=True)
    return {"theme": theme, "viewport": viewport_name, "states": results, "horizontal_overflow": False, "status": "PASS"}


async def _run_english_probe(page: Page) -> dict[str, Any]:
    state: dict[str, Any] = {"session": "expired", "logout_posts": 0}
    await _install_fixtures(page, state)
    await page.set_viewport_size({"width": 1440, "height": 900})
    await page.goto(f"{BASE_URL}/?theme=light&lang=en", wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_function("() => document.documentElement.lang === 'en'", timeout=5_000)
    await _refresh(page)
    if (await page.locator("#accountName").inner_text()).strip() != "Session expired":
        raise AssertionError("English expired-session copy did not project")
    if (await page.locator("#loginButton").inner_text()).strip() != "Sign in again":
        raise AssertionError("English recovery action did not project")
    return {"lang": "en", "expired_copy": "PASS", "status": "PASS"}


async def main() -> None:
    report: dict[str, Any] = {"base_url": BASE_URL, "views": {}, "status": "PASS"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme in THEMES:
                for viewport_name, width, height, mobile in VIEWPORTS:
                    page = await browser.new_page()
                    try:
                        key = f"{theme}-{viewport_name}"
                        report["views"][key] = await _run_view(
                            page,
                            theme=theme,
                            viewport_name=viewport_name,
                            width=width,
                            height=height,
                            mobile=mobile,
                        )
                    finally:
                        await page.close()
            page = await browser.new_page()
            try:
                report["english_probe"] = await _run_english_probe(page)
            finally:
                await page.close()
        finally:
            await browser.close()

    path = OUT_DIR / "account-session-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
