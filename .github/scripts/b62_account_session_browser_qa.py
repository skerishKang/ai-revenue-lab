from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Awaitable
from urllib.parse import urlparse

from playwright.async_api import Browser, Page, Playwright, Route, async_playwright


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
            await _fulfill_json(
                route,
                {
                    "ready": False,
                    "authenticated": False,
                    "history_ready": False,
                    "user": None,
                },
            )
            return

        authenticated = current == "signed_in"
        await _fulfill_json(
            route,
            {
                "ready": True,
                "authenticated": authenticated,
                "history_ready": authenticated,
                "project_files_ready": authenticated,
                "session_state": current,
                "user": (
                    {
                        "id": "usr_browser_account_fixture",
                        "email": "browser@example.test",
                        "name": USER_NAME,
                        "picture": "",
                    }
                    if authenticated
                    else None
                ),
            },
        )

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
        # Safety net only. The expired presentation probe suppresses the CTA
        # at capture phase; reaching this route means hermetic QA leaked into
        # an OAuth navigation.
        state["google_start_reads"] += 1
        await route.fulfill(status=204, body="")

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/auth/logout", logout)
    await page.route("**/api/projects", empty_projects)
    await page.route("**/api/conversations", empty_conversations)
    await page.route("**/auth/google/start", google_start)


def _initial_session(case: str) -> str:
    if case == "signed":
        return "signed_in"
    if case in {"expired", "english-expired"}:
        return "expired"
    return "unavailable"


async def _diagnostics(
    page: Page,
    state: dict[str, Any],
    page_errors: list[str],
    request_failures: list[str],
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "href": page.url,
        "fixture_state": dict(state),
        "page_errors": page_errors[-20:],
        "request_failures": request_failures[-20:],
    }
    try:
        diagnostic.update(
            await page.evaluate(
                """() => {
                  const root = document.querySelector('.sidebar-account');
                  const button = document.getElementById('loginButton');
                  const account = document.getElementById('accountName');
                  let auth = null;
                  try {
                    auth = window.PadiemProductCapabilities?.get?.().auth || null;
                  } catch (error) {
                    auth = { diagnosticError: String(error) };
                  }
                  return {
                    readyState: document.readyState,
                    title: document.title,
                    capabilityType: typeof window.PadiemProductCapabilities,
                    auth,
                    accountRoot: root ? {
                      hidden: root.hidden,
                      state: root.dataset.accountState || '',
                    } : null,
                    loginButton: button ? {
                      hidden: button.hidden,
                      disabled: button.disabled,
                      ariaDisabled: button.getAttribute('aria-disabled'),
                      text: button.textContent.trim(),
                    } : null,
                    accountName: account ? {
                      hidden: account.hidden,
                      text: account.textContent.trim(),
                    } : null,
                    mobileMenuPresent: Boolean(document.getElementById('mobileMenu')),
                    sidebarPresent: Boolean(document.getElementById('sidebar')),
                  };
                }"""
            )
        )
    except Exception as error:  # pragma: no cover - diagnostics must never mask primary failure
        diagnostic["evaluate_error"] = f"{type(error).__name__}: {error}"
    return diagnostic


async def _print_diagnostics(
    label: str,
    stage: str,
    page: Page,
    state: dict[str, Any],
    page_errors: list[str],
    request_failures: list[str],
) -> None:
    diagnostic = await _diagnostics(page, state, page_errors, request_failures)
    print(
        f"ACCOUNT_SESSION_DIAGNOSTIC={label}:{stage}:"
        + json.dumps(diagnostic, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


async def _open_sidebar(page: Page, mobile: bool, *, label: str) -> None:
    if not mobile:
        return

    opened = await page.evaluate(
        """() => {
          const menu = document.getElementById('mobileMenu');
          const sidebar = document.getElementById('sidebar');
          if (!menu || !sidebar) {
            return { ok: false, menu: Boolean(menu), sidebar: Boolean(sidebar) };
          }
          if (menu.getAttribute('aria-expanded') !== 'true') menu.click();
          return {
            ok: true,
            expanded: menu.getAttribute('aria-expanded'),
            sidebarHidden: sidebar.hidden,
          };
        }"""
    )
    if not opened.get("ok"):
        raise AssertionError(f"mobile sidebar controls missing at {label}: {opened}")

    await page.wait_for_function(
        """() => {
          const sidebar = document.getElementById('sidebar');
          if (!sidebar) return false;
          const style = getComputedStyle(sidebar);
          return style.display !== 'none' && style.visibility !== 'hidden';
        }""",
        timeout=5_000,
    )


async def _wait_state(page: Page, expected: str, *, label: str, timeout: int = 8_000) -> None:
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
    await page.wait_for_function(predicate, timeout=timeout)


async def _account_snapshot(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const root = document.querySelector('.sidebar-account');
          const button = document.getElementById('loginButton');
          const account = document.getElementById('accountName');
          if (!root || !button || !account) return { missing: true };
          const rect = button.getBoundingClientRect();
          return {
            missing: false,
            state: root.dataset.accountState || '',
            rootHidden: root.hidden,
            buttonHidden: button.hidden,
            buttonDisabled: button.disabled,
            ariaDisabled: button.getAttribute('aria-disabled'),
            buttonText: button.textContent.trim(),
            accountHidden: account.hidden,
            accountText: account.textContent.trim(),
            display: getComputedStyle(button).display,
            visibility: getComputedStyle(button).visibility,
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
          };
        }"""
    )


def _validate_target(snapshot: dict[str, Any], label: str) -> dict[str, float]:
    if snapshot.get("missing"):
        raise AssertionError(f"account DOM missing at {label}")
    if snapshot["buttonHidden"] or snapshot["display"] == "none" or snapshot["visibility"] == "hidden":
        raise AssertionError(f"account action not visible at {label}: {snapshot}")
    if float(snapshot["width"]) < 44 or float(snapshot["height"]) < 44:
        raise AssertionError(f"account target below 44px at {label}: {snapshot}")
    return {
        "x": round(float(snapshot["x"]), 2),
        "y": round(float(snapshot["y"]), 2),
        "width": round(float(snapshot["width"]), 2),
        "height": round(float(snapshot["height"]), 2),
    }


async def _assert_visible_state(
    page: Page,
    expected: str,
    *,
    label: str,
    button_text: str,
    account_text: str,
) -> dict[str, Any]:
    snapshot = await _account_snapshot(page)
    if snapshot.get("state") != expected or snapshot.get("rootHidden"):
        raise AssertionError(f"wrong account state at {label}: {snapshot}")
    if snapshot.get("buttonText") != button_text:
        raise AssertionError(f"wrong account action at {label}: {snapshot}")
    if snapshot.get("accountText") != account_text or snapshot.get("accountHidden"):
        raise AssertionError(f"wrong account copy at {label}: {snapshot}")
    if snapshot.get("buttonDisabled") or snapshot.get("ariaDisabled") != "false":
        raise AssertionError(f"account action must be operable at {label}: {snapshot}")
    return {
        "state": expected,
        "hidden": False,
        "target": _validate_target(snapshot, f"{label}-{expected}-action"),
        "status": "PASS",
    }


async def _click_dom(page: Page, selector: str, *, label: str) -> None:
    delivered = await page.evaluate(
        """(selector) => {
          const element = document.querySelector(selector);
          if (!element) return false;
          element.click();
          return true;
        }""",
        selector,
    )
    if not delivered:
        raise AssertionError(f"DOM click target missing at {label}: {selector}")


async def _assert_expired_recovery(
    page: Page,
    *,
    label: str,
    button_text: str,
    account_text: str,
) -> dict[str, Any]:
    snapshot = await page.evaluate(
        """({ buttonText, accountText }) => {
          const root = document.querySelector('.sidebar-account');
          const button = document.getElementById('loginButton');
          const account = document.getElementById('accountName');
          if (!root || !button || !account) return { missing: true };

          const rect = button.getBoundingClientRect();
          const before = {
            state: root.dataset.accountState || '',
            rootHidden: root.hidden,
            buttonHidden: button.hidden,
            buttonDisabled: button.disabled,
            ariaDisabled: button.getAttribute('aria-disabled'),
            buttonText: button.textContent.trim(),
            accountHidden: account.hidden,
            accountText: account.textContent.trim(),
            display: getComputedStyle(button).display,
            visibility: getComputedStyle(button).visibility,
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
          };

          window.__b62RecoveryClickProbe = { count: 0 };
          button.addEventListener('click', (event) => {
            window.__b62RecoveryClickProbe.count += 1;
            event.preventDefault();
            event.stopImmediatePropagation();
          }, { capture: true, once: true });
          button.focus({ preventScroll: true });
          const focused = document.activeElement === button;
          button.click();

          return {
            missing: false,
            before,
            expected: { buttonText, accountText },
            focused,
            clickCount: window.__b62RecoveryClickProbe.count,
          };
        }""",
        {"buttonText": button_text, "accountText": account_text},
    )
    if snapshot.get("missing"):
        raise AssertionError(f"expired account DOM missing at {label}")

    before = snapshot["before"]
    expected = snapshot["expected"]
    if before["state"] != "expired" or before["rootHidden"]:
        raise AssertionError(f"expired account state mismatch at {label}: {before}")
    if before["buttonText"] != expected["buttonText"] or before["accountText"] != expected["accountText"]:
        raise AssertionError(f"expired account copy mismatch at {label}: {before}")
    if before["accountHidden"] or before["buttonDisabled"] or before["ariaDisabled"] != "false":
        raise AssertionError(f"expired recovery action invalid at {label}: {before}")

    target = _validate_target(before, f"{label}-expired-action")
    if snapshot["focused"] is not True or int(snapshot["clickCount"]) != 1:
        raise AssertionError(f"expired recovery focus/click delivery failed at {label}: {snapshot}")

    return {
        "state": "expired",
        "hidden": False,
        "target": target,
        "focus": "PASS",
        "ui_clicks": int(snapshot["clickCount"]),
        "status": "PASS",
    }


async def _assert_no_overflow(page: Page, label: str) -> None:
    widths = await page.evaluate(
        "() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })"
    )
    if int(widths["scrollWidth"]) > int(widths["innerWidth"]) + 1:
        raise AssertionError(
            f"horizontal overflow at {label}: {widths['scrollWidth']}>{widths['innerWidth']}"
        )


async def _wait_counter(state: dict[str, Any], key: str, minimum: int, *, label: str) -> None:
    for _ in range(50):
        if int(state.get(key, 0)) >= minimum:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{key} did not reach {minimum} at {label}: {state.get(key, 0)}")


async def _bounded_cleanup(label: str, name: str, operation: Awaitable[Any]) -> None:
    try:
        await asyncio.wait_for(operation, timeout=2.0)
        print(f"ACCOUNT_SESSION_CLEANUP_OK={label}:{name}", flush=True)
    except Exception as error:  # pragma: no cover - cleanup must not hide the primary result
        print(
            f"ACCOUNT_SESSION_CLEANUP_WARN={label}:{name}:{type(error).__name__}:{error}",
            flush=True,
        )


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

    playwright: Playwright | None = None
    browser: Browser | None = None
    page: Page | None = None

    print(f"ACCOUNT_SESSION_CASE_START={label}", flush=True)
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: (
                None
                if "/auth/google/start" in request.url
                else request_failures.append(
                    f"{request.method} {request.url} :: {request.failure or 'request failed'}"
                )
            ),
        )

        await _install_static_font_stubs(page, stubbed_hosts)
        await _install_fixtures(page, state)

        suffix = f"&lang={lang}" if lang else ""
        await page.goto(
            f"{BASE_URL}/?theme={theme}{suffix}",
            wait_until="domcontentloaded",
            timeout=10_000,
        )
        print(f"ACCOUNT_SESSION_NAV_READY={label}:domcontentloaded", flush=True)

        await page.locator(".sidebar-account").wait_for(state="attached", timeout=5_000)
        await page.wait_for_function(
            "() => typeof window.PadiemProductCapabilities?.get === 'function'",
            timeout=5_000,
        )
        print(f"ACCOUNT_SESSION_BOOTSTRAP_READY={label}", flush=True)

        await _open_sidebar(page, mobile, label=label)
        print(f"ACCOUNT_SESSION_SIDEBAR_READY={label}", flush=True)

        try:
            await _wait_state(page, session, label=label)
        except Exception:
            await _print_diagnostics(
                label,
                "state-timeout",
                page,
                state,
                page_errors,
                request_failures,
            )
            raise
        print(f"ACCOUNT_SESSION_STATE_READY={label}:{session}", flush=True)

        result: dict[str, Any] = {
            "theme": theme,
            "viewport": viewport_name,
            "case": case,
            "fixture_boundary": "browser-route-fixtures-plus-bounded-lifecycle-dom-probe",
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
                page,
                "signed_in",
                label=label,
                button_text="로그아웃",
                account_text=USER_NAME,
            )
            await _click_dom(page, "#loginButton", label=f"{label}-logout")
            await _wait_counter(state, "logout_posts", 1, label=label)
            await _wait_state(page, "guest", label=f"{label}-logout-guest")
            result["guest"] = await _assert_visible_state(
                page,
                "guest",
                label=label,
                button_text="로그인",
                account_text="게스트",
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
            result["expired"] = await _assert_expired_recovery(
                page,
                label=label,
                button_text=expected_button,
                account_text=expected_account,
            )
            print(f"ACCOUNT_SESSION_EXPIRED_DOM_PASS={label}", flush=True)
            if state["google_start_reads"] != 0:
                raise AssertionError(f"expired browser QA escaped into OAuth navigation at {label}")
            result["recovery"] = {
                "ui_clicks": result["expired"]["ui_clicks"],
                "oauth_route_contract": "/auth/google/start",
                "google_start_navigations": 0,
                "real_google_oauth": 0,
                "navigation_suppressed_by_capture_fixture": True,
                "status": "PASS",
            }

        else:
            unavailable = await page.evaluate(
                """() => ({
                  rootHidden: document.querySelector('.sidebar-account')?.hidden === true,
                  buttonHidden: document.getElementById('loginButton')?.hidden === true,
                })"""
            )
            if not unavailable["rootHidden"] or not unavailable["buttonHidden"]:
                raise AssertionError(f"auth unavailable presentation must fail closed at {label}: {unavailable}")
            result["unavailable"] = {
                "state": "unavailable",
                "hidden": True,
                "status": "PASS",
            }

        await _assert_no_overflow(page, label)
        if page_errors or request_failures:
            raise AssertionError(
                f"browser errors at {label}: page_errors={page_errors}, request_failures={request_failures}"
            )

        print(f"ACCOUNT_SESSION_CASE_PASS={label}", flush=True)
        return result

    except Exception as error:
        print(
            f"ACCOUNT_SESSION_CASE_FAIL={label}:{type(error).__name__}:{error}",
            flush=True,
        )
        if page is not None:
            await _print_diagnostics(
                label,
                "exception",
                page,
                state,
                page_errors,
                request_failures,
            )
        raise
    finally:
        if page is not None:
            await _bounded_cleanup(label, "page", page.close())
        if browser is not None:
            await _bounded_cleanup(label, "browser", browser.close())
        if playwright is not None:
            await _bounded_cleanup(label, "playwright", playwright.stop())


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
