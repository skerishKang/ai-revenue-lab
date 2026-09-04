from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_AUTH_HISTORY_QA_BASE_URL", "http://127.0.0.1:8769")
OUT_DIR = Path(os.environ.get("B62_AUTH_HISTORY_QA_OUT_DIR", ".tmp/b62-auth-history-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
VIEWPORTS = (("desktop", 1440, 1000, False), ("mobile", 390, 844, True))
USER_NAME = "브라우저 계정 사용자"
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
PROBE_TIMEOUT_SECONDS = 20.0


async def _fulfill_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
        headers={"Cache-Control": "no-store"},
    )


async def _install_static_font_stubs(page: Page, stubbed_hosts: set[str]) -> None:
    async def stub_stylesheet(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic account/session QA: external decorative font fetch suppressed */\n",
            headers={"Cache-Control": "no-store"},
        )

    async def stub_font_binary(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", stub_stylesheet)
    await page.route("https://fonts.googleapis.com/**", stub_stylesheet)
    await page.route("https://fonts.gstatic.com/**", stub_font_binary)


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

    async def google_start(route: Route) -> None:
        state["google_start_reads"] += 1
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body="<!doctype html><html><head><title>OAuth recovery fixture</title></head><body>fixture</body></html>",
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/auth/logout", logout)
    await page.route("**/api/projects", empty_projects)
    await page.route("**/api/conversations", empty_conversations)
    await page.route("**/auth/google/start", google_start)


async def _open_sidebar(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click(timeout=5_000)
    await page.locator("#sidebar").wait_for(state="visible", timeout=5_000)


async def _wait_state(page: Page, expected: str, *, label: str) -> None:
    if expected == "unavailable":
        predicate = """() => {
          const root = document.querySelector('.sidebar-account');
          const button = document.getElementById('loginButton');
          const auth = window.PadiemProductCapabilities?.get?.().auth;
          return auth?.sessionState === 'unavailable'
            && root?.hidden === true
            && button?.hidden === true;
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
        raise AssertionError(f"trusted {expected} presentation did not settle at {label}") from error


async def _assert_target(page: Page, selector: str, label: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{label} has no visible target")
    if box["height"] < 44 or box["width"] < 44:
        raise AssertionError(f"{label} target below 44px: {box}")
    return {key: round(float(value), 2) for key, value in box.items()}


async def _assert_visible_state(
    page: Page,
    expected: str,
    *,
    label: str,
    button_text: str,
    account_text: str,
) -> dict[str, Any]:
    container = page.locator(".sidebar-account")
    button = page.locator("#loginButton")
    account = page.locator("#accountName")
    if await container.get_attribute("data-account-state") != expected:
        raise AssertionError(f"wrong account state at {label}")
    if (await button.inner_text()).strip() != button_text:
        raise AssertionError(f"wrong account action at {label}")
    if (await account.inner_text()).strip() != account_text or await account.is_hidden():
        raise AssertionError(f"wrong account copy at {label}")
    if await button.get_attribute("aria-disabled") != "false" or await button.is_disabled():
        raise AssertionError(f"account action must be operable at {label}")
    target = await _assert_target(page, "#loginButton", f"{label}-{expected}-action")
    return {"state": expected, "hidden": False, "target": target, "status": "PASS"}


async def _assert_no_overflow(page: Page, label: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {label}: {scroll_width}>{inner_width}")


async def _wait_counter(state: dict[str, Any], key: str, minimum: int, *, label: str) -> None:
    for _ in range(50):
        if int(state.get(key, 0)) >= minimum:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{key} did not reach {minimum} at {label}: {state.get(key, 0)}")


async def _safe_close(page: Page, browser: Any) -> None:
    try:
        await asyncio.wait_for(page.close(), timeout=3.0)
    except Exception:
        pass
    try:
        await asyncio.wait_for(browser.close(), timeout=3.0)
    except Exception:
        pass


async def _open_probe(
    playwright: Any,
    *,
    session: str,
    theme: str,
    width: int,
    height: int,
    mobile: bool,
    lang: str | None = None,
) -> tuple[Any, Page, dict[str, Any], set[str]]:
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page(viewport={"width": width, "height": height})
    state: dict[str, Any] = {
        "session": session,
        "logout_posts": 0,
        "history_reads": 0,
        "google_start_reads": 0,
    }
    stubbed_hosts: set[str] = set()
    try:
        await _install_static_font_stubs(page, stubbed_hosts)
        await _install_fixtures(page, state)
        suffix = f"&lang={lang}" if lang else ""
        await page.goto(f"{BASE_URL}/?theme={theme}{suffix}", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_function(
            "() => typeof window.PadiemProductCapabilities?.get === 'function' && document.querySelector('.sidebar-account')",
            timeout=5_000,
        )
        await _open_sidebar(page, mobile)
        await _wait_state(page, session, label=f"{theme}-{session}")
        return browser, page, state, stubbed_hosts
    except Exception:
        await _safe_close(page, browser)
        raise


async def _signed_logout_guest_probe(
    playwright: Any,
    *,
    theme: str,
    viewport_name: str,
    width: int,
    height: int,
    mobile: bool,
) -> dict[str, Any]:
    label = f"{theme}-{viewport_name}"
    browser, page, state, stubbed_hosts = await _open_probe(
        playwright,
        session="signed_in",
        theme=theme,
        width=width,
        height=height,
        mobile=mobile,
    )
    try:
        await _wait_counter(state, "history_reads", 1, label=label)
        await page.wait_for_function("() => document.getElementById('historySection')?.hidden === false", timeout=5_000)
        signed = await _assert_visible_state(
            page, "signed_in", label=label, button_text="로그아웃", account_text=USER_NAME
        )
        await page.locator("#loginButton").focus()
        await page.locator("#loginButton").click(timeout=5_000, no_wait_after=True)
        await _wait_counter(state, "logout_posts", 1, label=label)
        await _wait_state(page, "guest", label=f"{label}-logout-guest")
        guest = await _assert_visible_state(
            page, "guest", label=label, button_text="로그인", account_text="게스트"
        )
        await _assert_no_overflow(page, label)
        return {
            "signed_in": signed,
            "guest": guest,
            "logout": {"posts": state["logout_posts"], "returns_to": "guest", "status": "PASS"},
            "history_consumed_by_app": state["history_reads"] > 0,
            "stubbed_decorative_font_hosts": sorted(stubbed_hosts & STATIC_FONT_HOSTS),
            "status": "PASS",
        }
    finally:
        await _safe_close(page, browser)


async def _expired_recovery_probe(
    playwright: Any,
    *,
    theme: str,
    viewport_name: str,
    width: int,
    height: int,
    mobile: bool,
) -> dict[str, Any]:
    label = f"{theme}-{viewport_name}"
    browser, page, state, stubbed_hosts = await _open_probe(
        playwright,
        session="expired",
        theme=theme,
        width=width,
        height=height,
        mobile=mobile,
    )
    try:
        expired = await _assert_visible_state(
            page, "expired", label=label, button_text="다시 로그인", account_text="세션 만료"
        )
        await _assert_no_overflow(page, label)
        await page.locator("#loginButton").focus()
        await page.locator("#loginButton").click(timeout=5_000, no_wait_after=True)
        await _wait_counter(state, "google_start_reads", 1, label=label)
        return {
            "expired": expired,
            "recovery": {
                "google_start_navigations": state["google_start_reads"],
                "real_google_oauth": 0,
                "status": "PASS",
            },
            "stubbed_decorative_font_hosts": sorted(stubbed_hosts & STATIC_FONT_HOSTS),
            "status": "PASS",
        }
    finally:
        await _safe_close(page, browser)


async def _unavailable_probe(
    playwright: Any,
    *,
    theme: str,
    viewport_name: str,
    width: int,
    height: int,
    mobile: bool,
) -> dict[str, Any]:
    label = f"{theme}-{viewport_name}"
    browser, page, _, stubbed_hosts = await _open_probe(
        playwright,
        session="unavailable",
        theme=theme,
        width=width,
        height=height,
        mobile=mobile,
    )
    try:
        if not await page.locator(".sidebar-account").is_hidden() or not await page.locator("#loginButton").is_hidden():
            raise AssertionError(f"auth unavailable must fail closed at {label}")
        await _assert_no_overflow(page, label)
        return {
            "unavailable": {"state": "unavailable", "hidden": True, "status": "PASS"},
            "stubbed_decorative_font_hosts": sorted(stubbed_hosts & STATIC_FONT_HOSTS),
            "status": "PASS",
        }
    finally:
        await _safe_close(page, browser)


async def _run_view(
    playwright: Any,
    *,
    theme: str,
    viewport_name: str,
    width: int,
    height: int,
    mobile: bool,
) -> dict[str, Any]:
    key = f"{theme}-{viewport_name}"
    print(f"ACCOUNT_SESSION_QA_START={key}", flush=True)
    signed = await asyncio.wait_for(
        _signed_logout_guest_probe(
            playwright,
            theme=theme,
            viewport_name=viewport_name,
            width=width,
            height=height,
            mobile=mobile,
        ),
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    print(f"ACCOUNT_SESSION_QA_SIGNED_LOGOUT_GUEST_PASS={key}", flush=True)
    expired = await asyncio.wait_for(
        _expired_recovery_probe(
            playwright,
            theme=theme,
            viewport_name=viewport_name,
            width=width,
            height=height,
            mobile=mobile,
        ),
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    print(f"ACCOUNT_SESSION_QA_EXPIRED_RECOVERY_PASS={key}", flush=True)
    unavailable = await asyncio.wait_for(
        _unavailable_probe(
            playwright,
            theme=theme,
            viewport_name=viewport_name,
            width=width,
            height=height,
            mobile=mobile,
        ),
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    print(f"ACCOUNT_SESSION_QA_UNAVAILABLE_PASS={key}", flush=True)
    return {
        "theme": theme,
        "viewport": viewport_name,
        "states": {
            "signed_in": signed["signed_in"],
            "guest": signed["guest"],
            "logout": signed["logout"],
            "expired": expired["expired"],
            "recovery": expired["recovery"],
            "unavailable": unavailable["unavailable"],
        },
        "history_consumed_by_app": signed["history_consumed_by_app"],
        "decorative_font_network": "stubbed-before-network",
        "horizontal_overflow": False,
        "production_mutation": False,
        "status": "PASS",
    }


async def _run_english_probe(playwright: Any) -> dict[str, Any]:
    browser, page, _, stubbed_hosts = await _open_probe(
        playwright,
        session="expired",
        theme="light",
        width=1440,
        height=900,
        mobile=False,
        lang="en",
    )
    try:
        await page.wait_for_function("() => document.documentElement.lang === 'en'", timeout=5_000)
        if (await page.locator("#accountName").inner_text()).strip() != "Session expired":
            raise AssertionError("English expired-session copy did not project")
        if (await page.locator("#loginButton").inner_text()).strip() != "Sign in again":
            raise AssertionError("English recovery action did not project")
        await _assert_target(page, "#loginButton", "english-expired-action")
        return {
            "lang": "en",
            "expired_copy": "PASS",
            "stubbed_decorative_font_hosts": sorted(stubbed_hosts & STATIC_FONT_HOSTS),
            "status": "PASS",
        }
    finally:
        await _safe_close(page, browser)


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "fixture_boundary": "browser-route-fixtures-only",
        "state_documents": "isolated-by-trusted-auth-state",
        "decorative_font_network": "stubbed-before-network",
        "real_google_oauth": 0,
        "production_mutation": False,
        "views": {},
        "status": "PASS",
    }
    async with async_playwright() as playwright:
        for theme in THEMES:
            for viewport_name, width, height, mobile in VIEWPORTS:
                key = f"{theme}-{viewport_name}"
                report["views"][key] = await _run_view(
                    playwright,
                    theme=theme,
                    viewport_name=viewport_name,
                    width=width,
                    height=height,
                    mobile=mobile,
                )
        report["english_probe"] = await asyncio.wait_for(
            _run_english_probe(playwright), timeout=PROBE_TIMEOUT_SECONDS
        )

    path = OUT_DIR / "account-session-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
