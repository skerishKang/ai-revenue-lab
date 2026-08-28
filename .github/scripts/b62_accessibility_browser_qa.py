from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_A11Y_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get("B62_A11Y_QA_OUT_DIR", ".tmp/b62-accessibility-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_VISIBLE_JARGON = ("gemini", "openrouter", "poolside", "agnes", "provider", "모델:", "제공 경로:")


async def _stub_fonts(page: Page, seen: set[str]) -> None:
    async def css(route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic a11y QA font stub */\n")

    async def font(route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _semantic_snapshot(page: Page) -> dict:
    return await page.evaluate(
        """() => {
          const input = document.getElementById('messageInput');
          const label = document.querySelector('label[for="messageInput"]');
          const conversation = document.querySelector('.conversation');
          const nav = document.querySelector('nav.side-nav');
          const h1s = [...document.querySelectorAll('h1')].filter((el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
          });
          const emptyCopy = document.querySelector('.empty-copy');
          return {
            lang: document.documentElement.lang,
            visible_h1_count: h1s.length,
            nav_label: nav?.getAttribute('aria-label') || '',
            input_label: label?.textContent.trim() || '',
            conversation_live: conversation?.getAttribute('aria-live') || '',
            input_font_px: input ? parseFloat(getComputedStyle(input).fontSize) : 0,
            empty_copy_font_px: emptyCopy ? parseFloat(getComputedStyle(emptyCopy).fontSize) : 0,
          };
        }"""
    )


async def _interactive_audit(page: Page) -> dict:
    return await page.evaluate(
        """() => {
          const selector = 'button:not([disabled]), a[href], textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), [tabindex]:not([tabindex="-1"])';
          const items = [...document.querySelectorAll(selector)].filter((el) => {
            if (el.closest('[hidden]') || el.closest('[inert]')) return false;
            const s = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
          });
          const labelText = (el) => {
            const aria = (el.getAttribute('aria-label') || '').trim();
            if (aria) return aria;
            const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
            if (labelledBy) {
              const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent || '').join(' ').trim();
              if (text) return text;
            }
            if (el.id) {
              const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
              if (label?.textContent.trim()) return label.textContent.trim();
            }
            const text = (el.textContent || '').trim();
            if (text) return text;
            return (el.getAttribute('title') || '').trim();
          };
          return {
            count: items.length,
            unnamed: items.filter((el) => !labelText(el)).map((el) => el.id || el.outerHTML.slice(0, 120)),
            undersized: items.map((el) => {
              const r = el.getBoundingClientRect();
              return { id: el.id || '', tag: el.tagName, width: Math.round(r.width * 10) / 10, height: Math.round(r.height * 10) / 10, name: labelText(el) };
            }).filter((item) => item.width < 24 || item.height < 24),
          };
        }"""
    )


async def _no_overflow(page: Page, stage: str) -> None:
    widths = await page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    if widths[0] > widths[1] + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {widths}")


async def _focus_visible(page: Page) -> dict:
    await page.evaluate("() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); }")
    await page.keyboard.press("Tab")
    result = await page.evaluate(
        """() => {
          const el = document.activeElement;
          const s = el ? getComputedStyle(el) : null;
          return {
            id: el?.id || '',
            tag: el?.tagName || '',
            focus_visible: Boolean(el?.matches?.(':focus-visible')),
            outline_style: s?.outlineStyle || '',
            outline_width: s ? parseFloat(s.outlineWidth) || 0 : 0,
          };
        }"""
    )
    if not result["focus_visible"] or result["outline_style"] == "none" or result["outline_width"] < 2:
        raise AssertionError(f"keyboard focus indicator not visibly rendered: {result}")
    return result


async def _visible_jargon(page: Page) -> list[str]:
    body = (await page.locator("body").inner_text()).lower()
    return [term for term in FORBIDDEN_VISIBLE_JARGON if term in body]


async def _base_checks(page: Page, *, label: str) -> dict:
    semantic = await _semantic_snapshot(page)
    if semantic["lang"] != "ko":
        raise AssertionError(f"html lang must be ko: {semantic}")
    if semantic["visible_h1_count"] != 1:
        raise AssertionError(f"exactly one visible h1 required: {semantic}")
    if not semantic["nav_label"] or semantic["input_label"] != "메시지 입력":
        raise AssertionError(f"navigation/input accessible labels missing: {semantic}")
    if semantic["conversation_live"] != "polite":
        raise AssertionError(f"conversation live region missing: {semantic}")
    if semantic["input_font_px"] < 16:
        raise AssertionError(f"message input below 16px: {semantic}")
    if semantic["empty_copy_font_px"] < 15:
        raise AssertionError(f"first-use explanatory copy below 15px: {semantic}")

    interactive = await _interactive_audit(page)
    if interactive["unnamed"]:
        raise AssertionError(f"visible enabled controls without accessible names: {interactive['unnamed']}")
    if interactive["undersized"]:
        raise AssertionError(f"visible enabled targets below 24x24 CSS px: {interactive['undersized']}")

    jargon = await _visible_jargon(page)
    if jargon:
        raise AssertionError(f"provider/model jargon visible in ordinary first-use UI: {jargon}")

    await _no_overflow(page, label)
    focus = await _focus_visible(page)
    return {"semantic": semantic, "interactive": interactive, "focus": focus, "visible_jargon": jargon}


async def _desktop(page: Page) -> dict:
    seen_hosts: set[str] = set()
    unexpected_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe)
    await _stub_fonts(page, seen_hosts)
    await page.set_viewport_size({"width": 1440, "height": 1000})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("h1").wait_for(state="visible")

    base = await _base_checks(page, label="desktop-first-use")
    drawer = await page.evaluate(
        """() => ({
          sidebar_inert: document.getElementById('sidebar')?.inert === true,
          main_inert: document.querySelector('.main-panel')?.inert === true,
        })"""
    )
    if drawer["sidebar_inert"] or drawer["main_inert"]:
        raise AssertionError(f"desktop content must not be inert: {drawer}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)}")
    await page.screenshot(path=str(OUT_DIR / "desktop-a11y-first-use.png"), full_page=True)
    return {**base, "drawer": drawer, "stubbed_static_hosts": sorted(seen_hosts), "unexpected_external_hosts": sorted(unexpected_hosts)}


async def _mobile(page: Page) -> dict:
    seen_hosts: set[str] = set()
    unexpected_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe)
    await _stub_fonts(page, seen_hosts)
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("h1").wait_for(state="visible")

    closed = await page.evaluate(
        """() => ({
          sidebar_inert: document.getElementById('sidebar')?.inert === true,
          main_inert: document.querySelector('.main-panel')?.inert === true,
          expanded: document.getElementById('mobileMenu')?.getAttribute('aria-expanded'),
        })"""
    )
    if closed != {"sidebar_inert": True, "main_inert": False, "expanded": "false"}:
        raise AssertionError(f"closed mobile drawer accessibility state invalid: {closed}")

    base = await _base_checks(page, label="mobile-first-use")
    if base["focus"]["id"] != "mobileMenu":
        raise AssertionError(f"closed drawer captured initial keyboard focus: {base['focus']}")

    await page.keyboard.press("Enter")
    await page.wait_for_function(
        "() => document.querySelector('.app-shell')?.classList.contains('sidebar-open') && document.activeElement?.id === 'mobileClose'"
    )
    opened = await page.evaluate(
        """() => ({
          sidebar_inert: document.getElementById('sidebar')?.inert === true,
          main_inert: document.querySelector('.main-panel')?.inert === true,
          expanded: document.getElementById('mobileMenu')?.getAttribute('aria-expanded'),
          active: document.activeElement?.id || '',
        })"""
    )
    if opened != {"sidebar_inert": False, "main_inert": True, "expanded": "true", "active": "mobileClose"}:
        raise AssertionError(f"open mobile drawer accessibility state invalid: {opened}")
    await page.screenshot(path=str(OUT_DIR / "mobile-drawer-open.png"), full_page=True)

    await page.keyboard.press("Escape")
    await page.wait_for_function(
        "() => !document.querySelector('.app-shell')?.classList.contains('sidebar-open') && document.activeElement?.id === 'mobileMenu'"
    )
    escape_closed = await page.evaluate(
        """() => ({
          sidebar_inert: document.getElementById('sidebar')?.inert === true,
          main_inert: document.querySelector('.main-panel')?.inert === true,
          expanded: document.getElementById('mobileMenu')?.getAttribute('aria-expanded'),
          active: document.activeElement?.id || '',
        })"""
    )
    if escape_closed != {"sidebar_inert": True, "main_inert": False, "expanded": "false", "active": "mobileMenu"}:
        raise AssertionError(f"Escape did not restore mobile trigger focus: {escape_closed}")

    await page.keyboard.press("Enter")
    await page.wait_for_function("() => document.activeElement?.id === 'mobileClose'")
    await page.keyboard.press("Enter")
    await page.wait_for_function(
        "() => !document.querySelector('.app-shell')?.classList.contains('sidebar-open') && document.activeElement?.id === 'mobileMenu'"
    )
    button_closed = await page.evaluate(
        """() => ({
          sidebar_inert: document.getElementById('sidebar')?.inert === true,
          main_inert: document.querySelector('.main-panel')?.inert === true,
          expanded: document.getElementById('mobileMenu')?.getAttribute('aria-expanded'),
          active: document.activeElement?.id || '',
        })"""
    )
    if button_closed != {"sidebar_inert": True, "main_inert": False, "expanded": "false", "active": "mobileMenu"}:
        raise AssertionError(f"close button did not restore trigger focus: {button_closed}")

    await _no_overflow(page, "mobile-drawer-closed")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)}")
    await page.screenshot(path=str(OUT_DIR / "mobile-a11y-first-use.png"), full_page=True)
    return {
        **base,
        "closed": closed,
        "opened": opened,
        "escape_closed": escape_closed,
        "button_closed": button_closed,
        "stubbed_static_hosts": sorted(seen_hosts),
        "unexpected_external_hosts": sorted(unexpected_hosts),
    }


async def _reduced_motion(browser) -> dict:
    page = await browser.new_page(viewport={"width": 390, "height": 844})
    try:
        await page.emulate_media(reduced_motion="reduce")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        durations = await page.evaluate(
            """() => {
              const starter = getComputedStyle(document.querySelector('.starter'));
              const sidebar = getComputedStyle(document.getElementById('sidebar'));
              return { starter_transition: starter.transitionDuration, sidebar_transition: sidebar.transitionDuration };
            }"""
        )
        def max_ms(value: str) -> float:
            result = 0.0
            for part in value.split(','):
                part = part.strip()
                if part.endswith('ms'):
                    result = max(result, float(part[:-2]))
                elif part.endswith('s'):
                    result = max(result, float(part[:-1]) * 1000)
            return result
        if max_ms(durations["starter_transition"]) > 1 or max_ms(durations["sidebar_transition"]) > 1:
            raise AssertionError(f"reduced-motion still has material transition duration: {durations}")
        return durations
    finally:
        await page.close()


async def main() -> None:
    report = {
        "status": "RUNNING",
        "scope": "B62 first-use accessibility + mobile drawer focus",
        "model_selection": "DEFERRED",
        "real_provider_calls": 0,
        "core_b14_change": 0,
        "production_mutation": False,
        "views": {},
    }
    report_path = OUT_DIR / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                desktop = await browser.new_page(viewport={"width": 1440, "height": 1000})
                report["views"]["desktop"] = await _desktop(desktop)
                await desktop.close()
                mobile = await browser.new_page(viewport={"width": 390, "height": 844})
                report["views"]["mobile"] = await _mobile(mobile)
                await mobile.close()
                report["reduced_motion"] = await _reduced_motion(browser)
            finally:
                await browser.close()
        report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
