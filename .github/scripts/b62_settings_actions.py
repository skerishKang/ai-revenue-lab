"""#5560: the Settings screen is where the account and data actions live.

The admin hub, the conversation export and the sign-out moved out of the
sidebar bottom and into the existing Settings screen. The profile is the
one-step Settings entry, so these helpers open that same screen and drive the
controls in their new home.

The helpers click through the DOM on purpose: the mobile sidebar state and the
dialog state must not decide whether an action can be reached.
"""

from __future__ import annotations

from playwright.async_api import Page


async def open_settings(page: Page) -> None:
    """Open the existing Settings screen through the product's own entry."""
    await page.evaluate(
        """() => {
          const dialog = document.getElementById('settingsDialog');
          if (dialog && dialog.open) return;
          const profile = document.getElementById('accountProfileButton');
          if (profile) profile.click();
          if (dialog && !dialog.open) {
            const button = document.getElementById('settingsButton');
            if (button) button.click();
          }
          if (dialog && !dialog.open && typeof dialog.showModal === 'function') dialog.showModal();
        }"""
    )
    await page.locator("#settingsDialog").wait_for(state="visible", timeout=5_000)


async def close_settings(page: Page) -> None:
    """Close the Settings screen again."""
    await page.evaluate(
        """() => {
          const dialog = document.getElementById('settingsDialog');
          if (dialog && dialog.open) dialog.close();
        }"""
    )


async def settings_action_target(page: Page, selector: str, *, label: str) -> dict[str, float]:
    """Measure a control in the Settings screen as a touch target.

    The evidence is the same one the sidebar account action used to give: a
    visible control of at least 44 CSS px.
    """
    snapshot = await page.evaluate(
        """(selector) => {
          const button = document.getElementById(selector.replace('#', ''));
          if (!button) return { missing: true };
          const rect = button.getBoundingClientRect();
          return {
            missing: false,
            buttonHidden: button.hidden,
            buttonDisabled: button.disabled,
            display: getComputedStyle(button).display,
            visibility: getComputedStyle(button).visibility,
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
          };
        }""",
        selector,
    )
    if snapshot.get("missing"):
        raise AssertionError(f"settings action missing at {label}: {selector}")
    if snapshot["buttonHidden"] or snapshot["display"] == "none" or snapshot["visibility"] == "hidden":
        raise AssertionError(f"settings action not visible at {label}: {snapshot}")
    if float(snapshot["width"]) < 44 or float(snapshot["height"]) < 44:
        raise AssertionError(f"settings action target below 44px at {label}: {snapshot}")
    return {
        "x": round(float(snapshot["x"]), 2),
        "y": round(float(snapshot["y"]), 2),
        "width": round(float(snapshot["width"]), 2),
        "height": round(float(snapshot["height"]), 2),
    }


async def sign_out_via_settings(page: Page, *, label: str) -> None:
    """Sign out through Settings > Account.

    The server session invalidation and the local reset are unchanged; only
    the entry moved.
    """
    await open_settings(page)
    delivered = await page.evaluate(
        """() => {
          const button = document.getElementById('settingsLogoutButton');
          if (!button) return false;
          button.click();
          return true;
        }"""
    )
    if not delivered:
        raise AssertionError(f"settings sign-out action missing at {label}")
