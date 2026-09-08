from __future__ import annotations

from typing import Any

from playwright.async_api import Locator, Page


DIALOG = "#confirmDialog"
CANCEL = "#confirmDialogCancel"
CONFIRM = "#confirmDialogConfirm"
TITLE = "#confirmDialogTitle"
MESSAGE = "#confirmDialogMessage"


async def install_native_dialog_guard(page: Page, seen: list[str]) -> None:
    async def guard(dialog) -> None:
        seen.append(f"{dialog.type}:{dialog.message}")
        await dialog.dismiss()

    page.on("dialog", guard)


async def open_product_confirm(
    page: Page,
    trigger: Locator,
    *,
    title_contains: str,
    message_contains: str | None = None,
) -> None:
    await trigger.click()
    dialog = page.locator(DIALOG)
    await dialog.wait_for(state="visible", timeout=5_000)
    if await dialog.get_attribute("open") is None:
        raise AssertionError("product confirmation dialog is not modal-open")
    title = (await page.locator(TITLE).inner_text()).strip()
    if title_contains not in title:
        raise AssertionError(f"unexpected confirmation title: {title!r}")
    if message_contains:
        message = (await page.locator(MESSAGE).inner_text()).strip()
        if message_contains not in message:
            raise AssertionError(f"confirmation consequence copy missing {message_contains!r}: {message!r}")
    focused = await page.evaluate("document.activeElement && document.activeElement.id")
    if focused != "confirmDialogCancel":
        raise AssertionError(f"confirmation must focus safe cancel action first, got {focused!r}")


async def cancel_product_confirm(page: Page, *, escape: bool = False, expected_focus_id: str | None = None) -> None:
    if escape:
        await page.keyboard.press("Escape")
    else:
        await page.locator(CANCEL).click()
    await page.wait_for_function("() => document.getElementById('confirmDialog')?.open === false", timeout=5_000)
    if expected_focus_id:
        focused = await page.evaluate("document.activeElement && document.activeElement.id")
        if focused != expected_focus_id:
            raise AssertionError(f"confirmation focus return mismatch: {focused!r} != {expected_focus_id!r}")


async def accept_product_confirm(page: Page) -> None:
    await page.locator(CONFIRM).click()
    await page.wait_for_function("() => document.getElementById('confirmDialog')?.open === false", timeout=5_000)


async def assert_focus_trap(page: Page) -> dict[str, Any]:
    start = await page.evaluate("document.activeElement && document.activeElement.id")
    if start != "confirmDialogCancel":
        raise AssertionError(f"focus trap must start at cancel, got {start!r}")
    await page.keyboard.press("Shift+Tab")
    backward = await page.evaluate("document.activeElement && document.activeElement.id")
    if backward != "confirmDialogConfirm":
        raise AssertionError(f"Shift+Tab must wrap to destructive action, got {backward!r}")
    await page.keyboard.press("Tab")
    forward = await page.evaluate("document.activeElement && document.activeElement.id")
    if forward != "confirmDialogCancel":
        raise AssertionError(f"Tab must wrap back to cancel, got {forward!r}")
    return {"start": start, "backward": backward, "forward": forward}
