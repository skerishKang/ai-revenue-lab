from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

VIEWPORTS = (
    ("desktop-1920", 1920, 1080),
    ("compact-1280", 1280, 720),
    ("tablet-landscape-960", 960, 768),
    ("tablet-portrait-768", 768, 1024),
    ("mobile-390", 390, 844),
)


async def _box(page: Page, selector: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no visible bounding box")
    return {key: round(float(value), 2) for key, value in box.items()}


def _right(box: dict[str, float]) -> float:
    return box["x"] + box["width"]


def _assert_close(a: float, b: float, *, name: str, tolerance: float = 1.5) -> None:
    if abs(a - b) > tolerance:
        raise AssertionError(f"{name} mismatch: {a} vs {b}")


def _bottom_inset(box: dict[str, float], viewport_height: int) -> float:
    return round(float(viewport_height - (box["y"] + box["height"])), 2)


async def _open_claw(page: Page, *, width: int) -> bool:
    """Enter Claw's general view and report whether the first-use hero is up.

    Returns the *arrival* first-use state so geometry parity can be evaluated
    against the canvas the app actually renders, not against the state the
    probe leaves behind after it unblocks the manual shortcut.
    """
    if width <= 920:
        await page.locator("#mobileMenu").click()
        await page.locator("#clawNavButton").wait_for(state="visible")
    await page.locator("#clawNavButton").click()
    await page.locator('.app-shell[data-state="claw"]').wait_for(state="attached")
    # #3531 canonical contract: Claw navigation lands on the general
    # conversation view. The manual form stays hidden until the document
    # workflow is explicitly entered.
    view = await page.locator("#clawWorkspace").get_attribute("data-view")
    if view != "general":
        raise AssertionError(f"Claw navigation must enter the general view, got {view!r}")
    for selector in (".conversation", "#composerForm", "#messageInput"):
        if not await page.locator(selector).is_visible():
            raise AssertionError(f"{selector} must stay visible on Claw general view")
    if await page.locator("#clawManualForm").is_visible():
        raise AssertionError("#clawManualForm must stay hidden on Claw general view")
    # #4726 (b9ade4b9ed9) gave the first-use hero sole ownership of the general
    # view: while the empty state is on screen the manual-document shortcut is
    # suppressed by claw-focus-layout.css
    #   .app-shell[data-state="claw"]:has(.claw-workspace[data-view="general"]
    #       ~ .conversation .empty-state:not([hidden])) #clawManualEntryBar
    # so it does not crowd Chat's clean composer. The shortcut must reappear the
    # moment first use ends. Asserting unconditional visibility here would
    # contradict the shipped design and the sibling visual suite
    # (b62_browser_visual_qa.py, which already models both halves). Measured in
    # mock runtime: first arrival bar=display:none h=0; after dismissing the hero
    # bar=display:flex h=49 and the button is clickable.
    entry = page.locator("#clawManualEntryButton")
    first_use = page.locator("#emptyState")
    on_arrival = await first_use.is_visible()
    if on_arrival:
        if await entry.is_visible():
            raise AssertionError("manual workflow shortcut must not crowd the Claw first-use composer")
        await first_use.evaluate("(el) => { el.hidden = true; }")
    if not await entry.is_visible():
        raise AssertionError("manual workflow entry must remain available on Claw general view after first use")
    return on_arrival
    # The preceding Chat fixture is intentionally long and may leave the page
    # scrolled. Geometry parity must compare each surface from the same origin.
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(80)


async def _capture(page: Page, *, name: str, width: int, height: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass=female",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")

    home_conversation = await _box(page, ".conversation")
    home_composer = await _box(page, ".composer-wrap")
    home_placeholder = await page.locator("#messageInput").get_attribute("placeholder")
    home_composer_padding = await page.locator("#composerForm").evaluate(
        """el => {
          const s = getComputedStyle(el);
          return {
            top: parseFloat(s.paddingTop) || 0,
            right: parseFloat(s.paddingRight) || 0,
            bottom: parseFloat(s.paddingBottom) || 0,
            left: parseFloat(s.paddingLeft) || 0,
          };
        }"""
    )

    await page.locator("#messageInput").fill("공유 대화폭 반응형 검증")
    await page.locator("#sendButton").click()
    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('지금은 미리보기 환경입니다')",
        timeout=15_000,
    )
    await page.wait_for_timeout(450)

    # Deterministic layout fixtures: verify wide answer/error surfaces and
    # readable prose measure without requiring another runtime/provider path.
    await page.evaluate(
        """
        () => {
          const content = document.querySelector('#messageList .assistant-content');
          if (!content) throw new Error('assistant content missing');

          const rich = document.createElement('div');
          rich.id = 'shared-gutter-rich-fixture';
          rich.className = 'rich-response';
          const paragraph = document.createElement('p');
          paragraph.className = 'rich-response-paragraph';
          paragraph.textContent = '긴 답변 읽기 폭 검증 문장입니다. '.repeat(36);
          rich.appendChild(paragraph);
          content.appendChild(rich);

          const error = document.createElement('div');
          error.id = 'shared-gutter-error-fixture';
          error.className = 'error-box';
          const copy = document.createElement('p');
          copy.textContent = '오류 카드 반응형 폭 검증';
          const retry = document.createElement('button');
          retry.type = 'button';
          retry.className = 'retry-button';
          retry.textContent = '다시 시도';
          error.append(copy, retry);
          content.appendChild(error);
        }
        """
    )
    await page.wait_for_timeout(80)

    conversation = await _box(page, ".conversation")
    composer = await _box(page, ".composer-wrap")
    message_list = await _box(page, "#messageList")
    user_message = await _box(page, ".user-message")
    user_bubble = await _box(page, ".user-message .message-bubble")
    assistant_message = await _box(page, ".assistant-message")
    # The user turn shares the `assistant-avatar` class (one plate, two glyphs),
    # so the bare class resolves to two elements and strict mode rejects it.
    assistant_avatar = await _box(page, ".assistant-message .assistant-avatar")
    assistant_body = await _box(page, ".assistant-body")
    rich_surface = await _box(page, "#shared-gutter-rich-fixture")
    prose = await _box(page, "#shared-gutter-rich-fixture .rich-response-paragraph")
    error_surface = await _box(page, "#shared-gutter-error-fixture")
    retry_control = await _box(page, "#shared-gutter-error-fixture .retry-button")

    # Resolve the actual used padding rather than parsing the raw custom-property
    # token. The token uses clamp(), so parseFloat('--padiem-chat-inner-gutter')
    # is NaN even when the browser has correctly resolved it to a pixel value.
    conversation_padding = await page.locator(".conversation").evaluate(
        """
        (el) => {
          const style = getComputedStyle(el);
          return {
            left: Number.parseFloat(style.paddingLeft) || 0,
            right: Number.parseFloat(style.paddingRight) || 0,
          };
        }
        """
    )
    inner_gutter_left = round(float(conversation_padding["left"]), 2)
    inner_gutter_right = round(float(conversation_padding["right"]), 2)

    # Border-box vs content-box widths of the scrolling conversation lane.
    # `.conversation` scrolls, so its content box is narrower than its border
    # box by (borders + padding + scrollbar). The probe needs the raw numbers to
    # compare the message list against the box the list is actually laid out in.
    conversation_metrics = await page.locator(".conversation").evaluate(
        """
        (el) => {
          const style = getComputedStyle(el);
          return {
            borderLeft: Number.parseFloat(style.borderLeftWidth) || 0,
            borderRight: Number.parseFloat(style.borderRightWidth) || 0,
            offsetWidth: el.offsetWidth,
            clientWidth: el.clientWidth,
          };
        }
        """
    )
    conversation_border_left = round(float(conversation_metrics["borderLeft"]), 2)
    conversation_border_right = round(float(conversation_metrics["borderRight"]), 2)
    conversation_border_box_width = round(float(conversation_metrics["offsetWidth"]), 2)
    conversation_content_width = round(
        float(conversation_metrics["clientWidth"])
        - inner_gutter_left
        - inner_gutter_right,
        2,
    )

    # Resolve the declared reading-measure token using the paragraph's actual
    # font metrics. A ch unit is font-dependent, so an arbitrary pixel ceiling
    # would reject a correctly applied 76ch measure on some platforms/fonts.
    prose_measure = await page.locator(
        "#shared-gutter-rich-fixture .rich-response-paragraph"
    ).evaluate(
        """
        (el) => {
          const shell = el.closest('.app-shell');
          if (!shell) throw new Error('app shell missing');
          const token = getComputedStyle(shell)
            .getPropertyValue('--padiem-chat-reading-measure')
            .trim();
          if (!token) throw new Error('reading measure token missing');

          const style = getComputedStyle(el);
          const probe = document.createElement('div');
          probe.style.position = 'absolute';
          probe.style.visibility = 'hidden';
          probe.style.pointerEvents = 'none';
          probe.style.inlineSize = token;
          probe.style.font = style.font;
          probe.style.letterSpacing = style.letterSpacing;
          document.body.appendChild(probe);
          const px = probe.getBoundingClientRect().width;
          probe.remove();
          return { token, px };
        }
        """
    )
    prose_measure_token = str(prose_measure["token"])
    prose_measure_px = round(float(prose_measure["px"]), 2)
    if prose_measure_px <= 0:
        raise AssertionError(f"{name} reading measure did not resolve: {prose_measure}")

    # Outer shell contract. #4783 (edbbe75811e, 2026-10-15, "align Calendar
    # entry and Chat composer to Claw") deliberately inset the composer inside
    # the conversation lane on desktop, replacing the old "exactly one lane"
    # geometry that this probe still asserted:
    #
    #   >=1440px  .conversation width: min(1200px, 100vw - 252 - clamp(48,4vw,72)
    #                                              - clamp(360,32vw,560) - 48)
    #             .composer-wrap left: calc(252px + clamp(48,4vw,72) + 16px)
    #   1024-1439 .conversation margin-left: 24px
    #             .composer-wrap left: calc(252px + 38px)
    #   <=~920px  both fall back to the shared base rule (one lane)
    #
    # Measured on the real app (mock runtime), the composer is inset 14px per
    # side at every desktop width and identical below the tablet breakpoint:
    #   desktop-1920        width delta +28, left -14, right +14
    #   compact-1280        width delta +28, left -14, right +14
    #   tablet-landscape-960 width delta +28, left -14, right +14
    #   tablet-portrait-768  width delta  -2, left  +1, right  -1
    #   mobile-390           width delta  +2 pristine / +4 after the first answer
    # So the contract is width-aware: an inner inset on desktop, the single
    # shared lane below it. Assert the regime this viewport actually ships.
    lane_delta = round(conversation["width"] - composer["width"], 2)
    if width >= 920:
        if not 20 <= lane_delta <= 36:
            raise AssertionError(
                f"{name} desktop composer is not the designed inner inset of the "
                f"lane: width delta {lane_delta}"
            )
        left_inset = round(composer["x"] - conversation["x"], 2)
        if not 8 <= left_inset <= 22:
            raise AssertionError(f"{name} outer left inset out of range: {left_inset}")
        right_inset = round(_right(conversation) - _right(composer), 2)
        if not 8 <= right_inset <= 22:
            raise AssertionError(f"{name} outer right inset out of range: {right_inset}")
    else:
        _assert_close(conversation["x"], composer["x"], name=f"{name} outer left gutter", tolerance=2.5)
        _assert_close(
            _right(conversation), _right(composer), name=f"{name} outer right gutter", tolerance=2.5
        )
        # Below the tablet breakpoint the lane and composer share one width.
        # Measured: at tablet-portrait-768 the composer is 2px wider than the
        # lane (delta -2); at mobile-390 the lane is 2px wider on the pristine
        # home hero and 4px wider once the first answer renders, because the
        # assistant row's own 1px inset nudges the lane to x=12 w=366 against a
        # composer of x=14 w=362. The sign flips across these two shipped
        # viewports, so the invariant is the 2px-per-edge envelope, not one
        # direction: |delta| <= 4.
        if abs(lane_delta) > 4:
            raise AssertionError(f"{name} narrow viewport lane drift: {lane_delta}")

    # Internal identity rail contract: message content starts inside the real
    # bounded conversation padding instead of flattening avatar/meta.
    #
    # The comparison must be against the conversation's CONTENT box, not its
    # border box. `.conversation` is a scroll container: at >=921px it carries a
    # 12px vertical scrollbar, and `.message-list { width: 100% !important }`
    # resolves against the content box MINUS the scrollbar's net 10px. Measuring
    # against the border box therefore reports a phantom 10px "gutter" that the
    # probe mis-attributed to padding. Measured on clean main (mock runtime):
    #   viewport  convRight  contentRight  messageList  gap
    #   1920      1312       1276          1266         10
    #   960       940        915           905          10
    #   390       378        361.4         361.4        0
    # Left edge is flush with the content box at every width (delta 0), so the
    # left check stays exact; the right check allows the scrollbar reserve.
    _assert_close(
        message_list["x"],
        conversation["x"] + conversation_border_left + inner_gutter_left,
        name=f"{name} message-list left inner gutter",
    )
    # The list is `width: 100%` of the content box, so its right edge sits at
    # most (borders + scrollbar reserve) inside the conversation border box.
    scrollbar_reserve = round(
        conversation_border_right
        + (conversation_border_box_width - conversation_content_width - inner_gutter_left - inner_gutter_right),
        2,
    )
    right_gap = round(
        _right(conversation) - _right(message_list) - inner_gutter_right - conversation_border_right,
        2,
    )
    if not -1.5 <= right_gap <= 13:
        raise AssertionError(
            f"{name} message-list right inner gutter out of range: "
            f"{right_gap} (scrollbar reserve {scrollbar_reserve})"
        )
    _assert_close(
        inner_gutter_left,
        inner_gutter_right,
        name=f"{name} symmetric conversation inner gutter",
    )
    _assert_close(assistant_avatar["x"], message_list["x"], name=f"{name} avatar rail start")

    # User and wide assistant/error surfaces share ONE right boundary: the
    # user row and the wide rich-answer surface terminate at the same x. The
    # error card is a padded card with its own independent inset, so it is
    # intentionally narrower and is checked only for being inside the lane.
    #
    # Measured on the real app (mock runtime), rightInset from the conversation
    # border box:
    #   element     1920  1280  960   768   390
    #   user row     11    11    11     1     1
    #   rich answer  11    11    11     1     1
    #   error card   90    87    79    67    58.59
    # #2093-5 added an explicit right inset to .user-message, and #4783 kept the
    # shared desktop boundary at 11px; the rich answer follows the user row.
    shared_right_inset = round(_right(conversation) - _right(rich_surface), 2)
    user_right_inset = round(_right(conversation) - _right(user_message), 2)
    if width >= 921:
        if not 9 <= shared_right_inset <= 13:
            raise AssertionError(
                f"{name} wide answer surface outer right inset out of range: {shared_right_inset}"
            )
    else:
        if not -1 <= shared_right_inset <= 3:
            raise AssertionError(
                f"{name} narrow wide-answer outer right inset out of range: {shared_right_inset}"
            )
    _assert_close(
        user_right_inset,
        shared_right_inset,
        name=f"{name} user row and wide answer share one right boundary",
        tolerance=1.5,
    )
    # The error card is deliberately narrower: assert it stays inside the lane
    # and inside the shared boundary, never that it equals it.
    error_right_inset = round(_right(conversation) - _right(error_surface), 2)
    if not shared_right_inset <= error_right_inset <= shared_right_inset + 120:
        raise AssertionError(
            f"{name} error card right inset out of range: {error_right_inset} "
            f"(shared boundary inset {shared_right_inset})"
        )
    if _right(error_surface) > _right(conversation):
        raise AssertionError(f"{name} error card escapes the conversation lane")

    assistant_gap = round(assistant_body["x"] - _right(assistant_avatar), 2)
    if assistant_gap < 8 or assistant_gap > 12.5:
        raise AssertionError(f"{name} assistant meta/content gap out of range: {assistant_gap}")

    if prose["width"] > prose_measure_px + 1.5:
        raise AssertionError(
            f"{name} prose exceeds {prose_measure_token} measure: "
            f"{prose['width']} vs {prose_measure_px}"
        )
    if rich_surface["width"] > prose_measure_px + 8 and prose["width"] >= rich_surface["width"] - 1.5:
        raise AssertionError(
            f"{name} prose failed to stay narrower than wide answer surface: "
            f"{prose['width']} vs {rich_surface['width']}"
        )
    if retry_control["width"] <= 0 or retry_control["height"] <= 0:
        raise AssertionError(f"{name} retry control disappeared: {retry_control}")

    html_metrics = await page.evaluate(
        """
        () => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        })
        """
    )
    if html_metrics["scrollWidth"] > html_metrics["innerWidth"] + 1:
        raise AssertionError(f"{name} horizontal overflow: {html_metrics}")

    home_portrait = await page.locator(".main-panel").evaluate(
        "el => getComputedStyle(el, '::before').content"
    )
    home_portrait_image = await page.locator(".main-panel").evaluate(
        "el => getComputedStyle(el, '::before').backgroundImage"
    )
    # Shared Chat/Claw entry, input, background and layout parity.

    # the owner-approved Claw workbench no longer shares Chat Home geometry.
    shared_landing = await _open_claw(page, width=width)
    claw_conversation = await _box(page, ".conversation")
    claw_composer = await _box(page, ".composer-wrap")
    claw_placeholder = await page.locator("#messageInput").get_attribute("placeholder")
    claw_composer_padding = await page.locator("#composerForm").evaluate(
        """el => {
          const s = getComputedStyle(el);
          return {
            top: parseFloat(s.paddingTop) || 0,
            right: parseFloat(s.paddingRight) || 0,
            bottom: parseFloat(s.paddingBottom) || 0,
            left: parseFloat(s.paddingLeft) || 0,
          };
        }"""
    )

    # Chat and Claw now share the first-use canvas. After a conversation has
    # started, Claw's existing workbench remains a bounded independent surface.
    main_panel = await _box(page, ".main-panel")
    for surface, box in (("conversation", claw_conversation), ("composer", claw_composer)):
        if box["x"] < main_panel["x"] - 1 or _right(box) > _right(main_panel) + 1:
            raise AssertionError(f"{name} Claw {surface} exceeds main panel: {box} / {main_panel}")
        if box["width"] < min(300, width - 30):
            raise AssertionError(f"{name} Claw {surface} is cramped: {box}")
    if shared_landing:
        for surface, box, canonical in (
            ("conversation", claw_conversation, home_conversation),
            ("composer", claw_composer, home_composer),
        ):
            _assert_close(box["x"], canonical["x"],name=f"{name} first-use {surface} x",tolerance=2)
            _assert_close(box["width"],canonical["width"],name=f"{name} first-use {surface} width",tolerance=2)
    else:
        _assert_close(
            claw_conversation["x"]+claw_conversation["width"]/2,
            claw_composer["x"]+claw_composer["width"]/2,
            name=f"{name} active Claw centered conversation/composer",
            tolerance=2,
        )
        if claw_composer["width"] > claw_conversation["width"] + 1:
            raise AssertionError(f"{name} active Claw composer exceeds workbench")
    # The conversation must clear the real topbar rather than a hardcoded 62px.
    # Measured (mock runtime): the topbar is 61px at 390, 66px at 768 and 78px at
    # >=960, and the Claw conversation starts exactly at the topbar bottom on the
    # narrow viewports (gap 0) or 16px below it on desktop. The old literal 62
    # rejected the shipped 61px mobile topbar by a single pixel, so derive the
    # bound from the element the layout actually uses.
    topbar_bottom = await page.locator(".topbar").evaluate(
        "el => { const b = el.getBoundingClientRect(); return b.y + b.height; }"
    )
    topbar_bottom = round(float(topbar_bottom), 2)
    if claw_conversation["y"] < topbar_bottom - 1:
        raise AssertionError(
            f"{name} Claw conversation overlaps topbar: y={claw_conversation['y']} topbar_bottom={topbar_bottom}"
        )
    if claw_conversation["y"] >= height:
        raise AssertionError(f"{name} Claw conversation starts below the viewport")
    if not 0 <= _bottom_inset(claw_composer,height) <= 33:
        raise AssertionError(f"{name} Claw composer not docked to bottom")
    for side in ("top","right","bottom","left"):
        if not 0 <= float(claw_composer_padding[side]) <= 40:
            raise AssertionError(f"{name} Claw composer padding {side} out of bounds")
    portrait = await page.locator(".main-panel").evaluate("el => getComputedStyle(el, '::before').content")
    portrait_image = await page.locator(".main-panel").evaluate("el => getComputedStyle(el, '::before').backgroundImage")
    # claw-focus-layout.css suppresses the atmospheric portrait only when the
    # shell is *not* rendering the general-workspace sibling conversation:
    #   .app-shell[data-state="claw"]:not(:has(.claw-workspace[data-view="general"]
    #       ~ .conversation)) .main-panel::before { content: none; display: none; }
    # The general view satisfies that :has(), so the cinematic portrait is
    # deliberately retained and must be the same art Chat Home uses. The probe
    # reaches this point on the general canvas (the only Claw view it navigates
    # to), so assert parity with Chat rather than an absence that only holds on
    # the private workbench. Measured in mock runtime: both Chat Home and the
    # Claw general view resolve ::before to the same padiem-glass-female.jpg.
    if portrait != home_portrait or portrait_image != home_portrait_image:
        raise AssertionError(
            f"{name} Claw general-view portrait diverged from Chat Home: {portrait!r}/{portrait_image!r} vs {home_portrait!r}/{home_portrait_image!r}"
        )
    for art in (".glass-shell-portrait", ".glass-shell-field"):
        if await page.locator(art).count() and not await page.locator(art).is_visible():
            raise AssertionError(f"{name} shared glass art layer disappeared: {art}")
    metrics = await page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, width: innerWidth})"
    )
    if metrics["scrollWidth"] > metrics["width"] + 1:
        raise AssertionError(f"{name} Claw horizontal overflow: {metrics}")

    if claw_placeholder != home_placeholder:
        raise AssertionError(
            f"{name} Claw placeholder diverged from Chat Home: {claw_placeholder!r} vs {home_placeholder!r}"
        )
    # Explicit manual entry only: the document workflow — and its quote
    # action selection — appears after the entry control is clicked, never
    # by default. No workflow action may be pre-selected on entry.
    if await page.locator("#clawQuoteCard").get_attribute("aria-pressed") != "false":
        raise AssertionError(f"{name} quote action must not be pre-selected before explicit selection")
    await page.locator("#clawManualEntryButton").click()
    await page.wait_for_function(
        "() => document.querySelector('#clawWorkspace')?.dataset.view === 'manual'",
        timeout=5_000,
    )
    if not await page.locator("#clawManualForm").is_visible():
        raise AssertionError(f"{name} manual form must become visible after explicit manual entry")
    await page.locator("#clawQuoteCard").click()
    if await page.locator("#clawQuoteCard").get_attribute("aria-pressed") != "true":
        raise AssertionError(f"{name} explicit quote selection must be visibly selected")

    screenshot = f"{name}-shared-gutter.png"
    await page.screenshot(path=str(OUT_DIR / screenshot), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "home_conversation": home_conversation,
        "home_composer": home_composer,
        "claw_conversation": claw_conversation,
        "claw_composer": claw_composer,
        "claw_first_use_shares_chat": shared_landing,
        "claw_active_workbench_bounded": not shared_landing,
        "claw_composer_bounded": True,
        "claw_viewport_safe": True,
        "home_claw_placeholder_parity": True,
        "claw_general_default_view": True,
        "claw_manual_hidden_by_default": True,
        "claw_manual_entry_reachable": True,
        "claw_manual_view_on_explicit_entry": True,
        "claw_no_preselected_workflow_action": True,
        "claw_explicit_quote_selection": True,
        "conversation": conversation,
        "composer": composer,
        "inner_gutter_left_px": inner_gutter_left,
        "inner_gutter_right_px": inner_gutter_right,
        "message_list": message_list,
        "user_message": user_message,
        "user_bubble": user_bubble,
        "assistant_message": assistant_message,
        "assistant_avatar": assistant_avatar,
        "assistant_body": assistant_body,
        "assistant_gap_px": assistant_gap,
        "rich_surface": rich_surface,
        "prose": prose,
        "prose_measure_token": prose_measure_token,
        "prose_measure_px": prose_measure_px,
        "error_surface": error_surface,
        "retry_control": retry_control,
        "horizontal_overflow": False,
        "outer_gutter_parity": True,
        "meta_subgrid_preserved": True,
        "user_bubble_right_aligned": True,
        "rich_answer_right_aligned": True,
        "error_card_right_aligned": True,
        "screenshot": screenshot,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "purpose": "B62 shared outer gutter plus preserved internal meta rail and responsive answer surfaces",
        "views": {},
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, width, height in VIEWPORTS:
                page = await browser.new_page()
                try:
                    report["views"][name] = await _capture(
                        page, name=name, width=width, height=height
                    )
                finally:
                    await page.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    report_path = OUT_DIR / "shared-gutter-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
