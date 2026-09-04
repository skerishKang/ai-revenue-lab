from __future__ import annotations

import argparse
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
VIEWPORTS = {
    "desktop": (1440, 1000, False),
    "mobile": (390, 844, True),
}
CASES = ("signed", "expired", "unavailable", "english-expired")
USER_NAME = "브라우저 계정 사용자"
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})


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
        raise AssertionError(f"trusted {expected} presentation did not settle at {label}; href={page.url}") from error


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


def _initial_session(case: str) -> str:
    if case == "signed":
        return "signed_in"
    if case in {"expired", "english-expired"}:
        return "expired"
    return "unavailable"


async def _bootstrap_diagnostics(page: Page, page_errors: list[str], request_failures: list[str]) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "href": page.url,
        "page_errors": page_errors[-20:],
        "request_failures": request_failures[-20:],
    }
    try:
        diagnostic.update(await page.evaluate(
            """() => ({
              readyState: document.readyState,
              title: document.title,
              sidebarAccountPresent: Boolean(document.querySelector('.sidebar-account')),
              loginButtonPresent: Boolean(document.getElementById('loginButton')),
              capabilityType: typeof window.PadiemProductCapabilities,
              scripts: Array.from(document.scripts).map((script) => ({ src: script.src, readyState: script.readyState || null })),
            })"""
        ))
    except Exception as error:
        diagnostic["diagnostic_evaluate_error"] = f"{type(error).__name__}: {error}"
    return diagnostic


async def _run_case(theme: str, viewport_name: str, case: str) -> dict[str, Any]:
    if theme not in THEMES:
        raise ValueError(f"unsupported theme: {theme}")
    if viewport_name not in VIEWPORTS:
        raise ValueError(f"unsupported viewport: {viewport_name}")
    if case not in CASES:
        raise ValueError(f"unsupported case: {case}")

    width, height, mobile = VIEWPORTS[viewport_name]
    lang = "en" if case == "english-expired" else None
    session = _initial_session(case)
    label = f"{theme}-{viewport_name}-{case}"
    state: dict[str, Any] = {
        "session": session,
        "logout_posts": 0,
        "history_reads": 0,
        "google_start_reads": 0,
    }
    stubbed_hosts: set[str] = set()
    page_errors: list[str] = []
    request_failures: list[str] = []

    print(f"ACCOUNT_SESSION_CASE_START={label}", flush=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: request_failures.append(
                f"{request.method} {request.url} :: {request.failure or 'request failed'}"
            ),
        )
        try:
            await _install_static_font_stubs(page, stubbed_hosts)
            await _install_fixtures(page, state)
            suffix = f"&lang={lang}" if lang else ""
            await page.goto(f"{BASE_URL}/?theme={theme}{suffix}", wait_until="domcontentloaded", timeout=30_000)
            try:
                await page.locator(".sidebar-account").wait_for(state="attached", timeout=2_000)
                await page.wait_for_function(
                    "() => typeof window.PadiemProductCapabilities?.get === 'function'",
                    timeout=5_000,
                )
            except Exception as error:
                diagnostic = await _bootstrap_diagnostics(page, page_errors, request_failures)
                print(
                    "ACCOUNT_SESSION_BOOTSTRAP_DIAGNOSTIC="
                    + json.dumps(diagnostic, ensure_ascii=False, sort_keys=True),
                    flush=True,
                )
                raise AssertionError(
                    f"account/session bootstrap did not expose product capabilities at {label}"
                ) from error

            await _open_sidebar(page, mobile)
            await _wait_state(page, session, label=label)

            result: dict[str, Any] = {
                "theme": theme,
                "viewport": viewport_name,
                "case": case,
                "fixture_boundary": "browser-route-fixtures-only",
                "decorative_font_network": "stubbed-before-network",
                "stubbed_decorative_font_hosts": sorted(stubbed_hosts & STATIC_FONT_HOSTS),
                "real_google_oauth": 0,
                "production_mutation": False,
                "horizontal_overflow": False,
                "page_errors": page_errors,
                "request_failures": request_failures,
                "status": "PASS",
            }

            if case == "signed":
                await _wait_counter(state, "history_reads", 1, label=label)
                await page.wait_for_function(
                    "() => document.getElementById('historySection')?.hidden === false",
                    timeout=5_000,
                )
                result["signed_in"] = await _assert_visible_state(
                    page, "signed_in", label=label, button_text="로그아웃", account_text=USER_NAME
                )
                await page.locator("#loginButton").focus()
                await page.locator("#loginButton").click(timeout=5_000, no_wait_after=True)
                await _wait_counter(state, "logout_posts", 1, label=label)
                await _wait_state(page, "guest", label=f"{label}-logout-guest")
                result["guest"] = await _assert_visible_state(
                    page, "guest", label=label, button_text="로그인", account_text="게스트"
                )
                result["logout"] = {
                    "posts": state["logout_posts"],
                    "returns_to": "guest",
                    "status": "PASS",
                }
                result["history_consumed_by_app"] = state["history_reads"] > 0

            elif case in {"expired", "english-expired"}:
                expected_account = "Session expired" if lang == "en" else "세션 만료"
                expected_button = "Sign in again" if lang == "en" else "다시 로그인"
                result["expired"] = await _assert_visible_state(
                    page,
                    "expired",
                    label=label,
                    button_text=expected_button,
                    account_text=expected_account,
                )
                await page.locator("#loginButton").focus()
                await page.locator("#loginButton").click(timeout=5_000, no_wait_after=True)
                await _wait_counter(state, "google_start_reads", 1, label=label)
                result["recovery"] = {
                    "google_start_navigations": state["google_start_reads"],
                    "real_google_oauth": 0,
                    "status": "PASS",
                }

            else:
                if not await page.locator(".sidebar-account").is_hidden():
                    raise AssertionError(f"auth unavailable account container must fail closed at {label}")
                if not await page.locator("#loginButton").is_hidden():
                    raise AssertionError(f"auth unavailable action must fail closed at {label}")
                result["unavailable"] = {
                    "state": "unavailable",
                    "hidden": True,
                    "status": "PASS",
                }

            await _assert_no_overflow(page, label)
            print(f"ACCOUNT_SESSION_CASE_PASS={label}", flush=True)
            return result
        finally:
            await page.close()
            await browser.close()


def _write_report(report: dict[str, Any], theme: str, viewport: str, case: str) -> Path:
    safe_case = case.replace("-", "_")
    path = OUT_DIR / f"account-session-{theme}-{viewport}-{safe_case}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one isolated B62 account/session browser QA case")
    parser.add_argument("--theme", choices=THEMES, default="light")
    parser.add_argument("--viewport", choices=tuple(VIEWPORTS), default="desktop")
    parser.add_argument("--case", choices=CASES, required=True)
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    report = await _run_case(args.theme, args.viewport, args.case)
    path = _write_report(report, args.theme, args.viewport, args.case)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"ACCOUNT_SESSION_REPORT={path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
