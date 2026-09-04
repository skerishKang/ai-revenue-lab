from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Page, Route, async_playwright


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
        state["history_reads"] += 1
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


async def _wait_product_state(page: Page, expected: str, *, name: str) -> None:
    if expected == "unavailable":
        predicate = """() => {
          const root = document.querySelector('.sidebar-account');
          const button = document.getElementById('loginButton');
          const auth = window.PadiemProductCapabilities?.get?.().auth;
          return auth?.sessionState === 'unavailable' && root?.hidden === true && button?.hidden === true;
        }"""
    else:
        predicate = f"""() => {{
          const root = document.querySelector('.sidebar-account');
          const auth = window.PadiemProductCapabilities?.get?.().auth;
          return auth?.sessionState === {expected!r}
            && root?.dataset.accountState === {expected!r}
            && root?.hidden === false;
        }}"""
    try:
        await page.wait_for_function(predicate, timeout=5_000)
    except Exception as error:
        snapshot = await _snapshot(page)
        raise AssertionError(
            f"trusted {expected} presentation did not settle at {name}; "
            f"snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
        ) from error


async def _open_state_page(
    browser: Browser,
    *,
    session: str,
    theme: str,
    width: int,
    height: int,
    mobile: bool,
    name: str,
    lang: str | None = None,
) -> tuple[Page, dict[str, Any]]:
    state: dict[str, Any] = {"session": session, "logout_posts": 0, "history_reads": 0}
    page = await browser.new_page()
    try:
        await _install_fixtures(page, state)
        await page.set_viewport_size({"width": width, "height": height})
        suffix = f"&lang={lang}" if lang else ""
        await page.goto(f"{BASE_URL}/?theme={theme}{suffix}", wait_until="domcontentloaded", timeout=30_000)
        await page.locator(".sidebar-account").wait_for(state="attached", timeout=5_000)
        await page.wait_for_function(
            "() => typeof window.PadiemProductCapabilities?.get === 'function'",
            timeout=5_000,
        )
        await _open_sidebar(page, mobile)
        await _wait_product_state(page, session, name=name)
        return page, state
    except Exception:
        await page.close()
        raise


async def _assert_visible_state(
    page: Page,
    expected: str,
    *,
    name: str,
    button_text: str,
    account_text: str,
) -> dict[str, Any]:
    container = page.locator(".sidebar-account")
    button = page.locator("#loginButton")
    account = page.locator("#accountName")
    snapshot = await _snapshot(page)
    if await container.get_attribute("data-account-state") != expected:
        raise AssertionError(f"wrong account state at {name}; snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}")
    if (await button.inner_text()).strip() != button_text:
        raise AssertionError(f"wrong account action at {name}; snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}")
    if (await account.inner_text()).strip() != account_text or await account.is_hidden():
        raise AssertionError(f"wrong account copy at {name}; snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}")
    if await button.get_attribute("aria-disabled") != "false" or await button.is_disabled():
        raise AssertionError(f"account action must be operable at {name}; snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}")
    target = await _assert_target(page, "#loginButton", f"{name}-{expected}-action")
    return {"state": expected, "hidden": False, "target": target, "snapshot": snapshot, "status": "PASS"}


async def _wait_history_consumed(state: dict[str, Any], *, label: str) -> None:
    for _ in range(50):
        if state["history_reads"] > 0:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"app auth did not consume signed-in history readiness at {label}")


async def _run_view(
    browser: Browser,
    *,
    theme: str,
    viewport_name: str,
    width: int,
    height: int,
    mobile: bool,
) -> dict[str, Any]:
    label = f"{theme}-{viewport_name}"
    results: dict[str, Any] = {}

    guest_page, _ = await _open_state_page(
        browser,
        session="guest",
        theme=theme,
        width=width,
        height=height,
        mobile=mobile,
        name=f"{label}-guest",
    )
    try:
        results["guest"] = await _assert_visible_state(
            guest_page, "guest", name=label, button_text="로그인", account_text="게스트"
        )
    finally:
        await guest_page.close()

    expired_page, _ = await _open_state_page(
        browser,
        session="expired",
        theme=theme,
        width=width,
        height=height,
        mobile=mobile,
        name=f"{label}-expired",
    )
    try:
        results["expired"] = await _assert_visible_state(
            expired_page, "expired", name=label, button_text="다시 로그인", account_text="세션 만료"
        )
        await expired_page.screenshot(path=str(OUT_DIR / f"account-session-{label}-expired.png"), full_page=True)
    finally:
        await expired_page.close()

    signed_page, signed_state = await _open_state_page(
        browser,
        session="signed_in",
        theme=theme,
        width=width,
        height=height,
        mobile=mobile,
        name=f"{label}-signed-in",
    )
    try:
        await _wait_history_consumed(signed_state, label=label)
        await signed_page.wait_for_function(
            "() => document.getElementById('historySection')?.hidden === false",
            timeout=5_000,
        )
        results["signed_in"] = await _assert_visible_state(
            signed_page, "signed_in", name=label, button_text="로그아웃", account_text=USER_NAME
        )
        await signed_page.locator("#loginButton").focus()
        await signed_page.locator("#loginButton").click(timeout=5_000, no_wait_after=True)
        try:
            await signed_page.wait_for_function(
                """() => {
                  const root = document.querySelector('.sidebar-account');
                  const button = document.getElementById('loginButton');
                  const account = document.getElementById('accountName');
                  return root?.dataset.accountState === 'guest'
                    && root?.hidden === false
                    && button?.textContent.trim() === '로그인'
                    && account?.hidden === false
                    && account?.textContent.trim() === '게스트';
                }""",
                timeout=5_000,
            )
        except Exception as error:
            snapshot = await _snapshot(signed_page)
            raise AssertionError(
                f"logout did not settle to guest at {label}; "
                f"snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
            ) from error
        if signed_state["logout_posts"] != 1:
            raise AssertionError(f"logout must POST once at {label}: {signed_state['logout_posts']}")
        results["logout"] = {"posts": signed_state["logout_posts"], "returns_to": "guest", "status": "PASS"}
        await signed_page.screenshot(path=str(OUT_DIR / f"account-session-{label}-logout.png"), full_page=True)
    finally:
        await signed_page.close()

    unavailable_page, _ = await _open_state_page(
        browser,
        session="unavailable",
        theme=theme,
        width=width,
        height=height,
        mobile=mobile,
        name=f"{label}-unavailable",
    )
    try:
        snapshot = await _snapshot(unavailable_page)
        if not await unavailable_page.locator(".sidebar-account").is_hidden() or not await unavailable_page.locator("#loginButton").is_hidden():
            raise AssertionError(
                f"auth unavailable must fail closed at {label}; "
                f"snapshot={json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
            )
        results["unavailable"] = {"state": "unavailable", "hidden": True, "snapshot": snapshot, "status": "PASS"}
        await _assert_no_overflow(unavailable_page, label)
    finally:
        await unavailable_page.close()

    return {
        "theme": theme,
        "viewport": viewport_name,
        "states": results,
        "horizontal_overflow": False,
        "status": "PASS",
    }


async def _run_english_probe(browser: Browser) -> dict[str, Any]:
    page, _ = await _open_state_page(
        browser,
        session="expired",
        theme="light",
        width=1440,
        height=900,
        mobile=False,
        name="english-expired",
        lang="en",
    )
    try:
        await page.wait_for_function("() => document.documentElement.lang === 'en'", timeout=5_000)
        if (await page.locator("#accountName").inner_text()).strip() != "Session expired":
            raise AssertionError("English expired-session copy did not project")
        if (await page.locator("#loginButton").inner_text()).strip() != "Sign in again":
            raise AssertionError("English recovery action did not project")
        return {"lang": "en", "expired_copy": "PASS", "status": "PASS"}
    finally:
        await page.close()


async def main() -> None:
    report: dict[str, Any] = {"base_url": BASE_URL, "views": {}, "status": "PASS"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme in THEMES:
                for viewport_name, width, height, mobile in VIEWPORTS:
                    key = f"{theme}-{viewport_name}"
                    report["views"][key] = await _run_view(
                        browser,
                        theme=theme,
                        viewport_name=viewport_name,
                        width=width,
                        height=height,
                        mobile=mobile,
                    )
            report["english_probe"] = await _run_english_probe(browser)
        finally:
            await browser.close()

    path = OUT_DIR / "account-session-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
