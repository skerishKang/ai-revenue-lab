/* Shared PADIEM chip tooltip behaviour.
 *
 * One floating chip for the whole product. Any element carrying
 * `data-padiem-tooltip="<label>"` shows it on pointer entry and on keyboard
 * focus. The native browser `title` popup is intentionally not used, so the
 * owner never sees two hints at once.
 *
 * Contract (owner decision 2026-10-20):
 *   - appears within 100-150ms of pointer entry
 *   - disappears quickly on pointer leave
 *   - sits 6-8px away from the icon it describes
 *   - stays reachable by keyboard focus and on touch devices
 *   - reuses the PADIEM status-chip look (shared-tooltip.css)
 */
(() => {
  "use strict";

  const SHOW_DELAY_MS = 120;
  const HIDE_DELAY_MS = 70;
  const OFFSET_PX = 7;

  let bubble = null;
  let showTimer = null;
  let hideTimer = null;
  let currentAnchor = null;
  const tooltipId = "padiem-shared-tooltip";

  function ensureBubble() {
    if (bubble && bubble.isConnected) return bubble;
    bubble = document.createElement("div");
    bubble.className = "padiem-tooltip";
    bubble.id = tooltipId;
    bubble.setAttribute("role", "tooltip");
    bubble.setAttribute("aria-hidden", "true");
    bubble.dataset.padiemTooltipState = "hidden";
    document.body.appendChild(bubble);
    return bubble;
  }

  function labelFor(anchor) {
    const value = anchor.getAttribute("data-padiem-tooltip");
    return typeof value === "string" ? value.trim() : "";
  }

  /* #8021: the chip must not cover a button — above the send button it used
   * to land on the composer status pill stacked right above it. The anchor
   * itself is never a collision; the first candidate that fits the viewport
   * and clears every button wins. */
  function buttonUnder(anchor, left, top, size) {
    const box = {left, top, right: left + size.width, bottom: top + size.height};
    const scope = anchor.closest("form") || document;
    for (const button of scope.querySelectorAll("button")) {
      if (button === anchor || button.hidden) continue;
      const r = button.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      if (box.left < r.right && r.left < box.right
          && box.top < r.bottom && r.top < box.bottom) return r;
    }
    return null;
  }

  function place(anchor) {
    const node = ensureBubble();
    const rect = anchor.getBoundingClientRect();
    node.style.visibility = "hidden";
    node.style.left = "0px";
    node.style.top = "0px";
    const size = node.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;
    const clampLeft = (left) => Math.max(6, Math.min(left, viewportWidth - size.width - 6));
    const centerX = clampLeft(rect.left + (rect.width / 2) - (size.width / 2));
    const aboveY = rect.top - size.height - OFFSET_PX;
    const belowY = rect.bottom + OFFSET_PX;
    const fits = (top) => top >= 6 && top + size.height <= viewportHeight - 6;

    const candidates = [{left: centerX, top: aboveY}];
    const blocker = fits(aboveY) ? buttonUnder(anchor, centerX, aboveY, size) : null;
    if (blocker) {
      candidates.push({left: clampLeft(blocker.left - size.width - OFFSET_PX), top: aboveY});
      candidates.push({left: clampLeft(blocker.right + OFFSET_PX), top: aboveY});
    }
    candidates.push({left: centerX, top: belowY});

    let placed = null;
    for (const candidate of candidates) {
      if (!fits(candidate.top)) continue;
      if (!buttonUnder(anchor, candidate.left, candidate.top, size)) {
        placed = candidate;
        break;
      }
    }
    if (!placed) {
      placed = {left: centerX, top: aboveY < 6 ? belowY : aboveY};
    }
    node.style.left = Math.round(placed.left) + "px";
    node.style.top = Math.round(placed.top) + "px";
    node.style.visibility = "";
  }

  function show(anchor) {
    const label = labelFor(anchor);
    if (!label) return;
    if (currentAnchor && currentAnchor !== anchor) {
      detach(currentAnchor);
    }
    const node = ensureBubble();
    currentAnchor = anchor;
    node.textContent = label;
    place(anchor);
    node.dataset.padiemTooltipState = "visible";
    node.setAttribute("aria-hidden", "false");
    anchor.setAttribute("aria-describedby", tooltipId);
  }

  function hide() {
    // A dismissed tooltip must not come back through a pending show timer
    // (e.g. the pointer entered right before a click dismissed it).
    window.clearTimeout(showTimer);
    window.clearTimeout(hideTimer);
    if (!bubble) return;
    bubble.dataset.padiemTooltipState = "hidden";
    bubble.setAttribute("aria-hidden", "true");
    if (currentAnchor) {
      currentAnchor.removeAttribute("aria-describedby");
      currentAnchor = null;
    }
  }

  /* #8021: a shown chip must not outlive the interaction that triggered it.
   * Pressing anywhere closes it (a touch on the anchor itself keeps its tap
   * toggle), and the first keystroke in any field closes it immediately.
   * Focus moves away are already covered by the anchor's own blur. */
  function onDocumentPointerDown(event) {
    if (!currentAnchor) return;
    if (event.pointerType === "touch" && currentAnchor.contains(event.target)) return;
    hide();
  }

  function onDocumentInput() {
    hide();
  }

  let dismissBound = false;

  function ensureDismissListeners() {
    if (dismissBound) return;
    dismissBound = true;
    document.addEventListener("pointerdown", onDocumentPointerDown, true);
    document.addEventListener("input", onDocumentInput, true);
  }

  function detach(anchor) {
    anchor.removeEventListener("pointerenter", onEnter);
    anchor.removeEventListener("pointerleave", onLeave);
    anchor.removeEventListener("focus", onFocus);
    anchor.removeEventListener("blur", onBlur);
    anchor.removeEventListener("click", onClick);
  }

  function onEnter(event) {
    if (event.pointerType === "touch") return;
    // The anchor is captured now: event.currentTarget is null once the
    // dispatch finished, and the show runs in a timer.
    const anchor = event.currentTarget;
    window.clearTimeout(hideTimer);
    window.clearTimeout(showTimer);
    showTimer = window.setTimeout(() => show(anchor), SHOW_DELAY_MS);
  }

  function onLeave() {
    window.clearTimeout(showTimer);
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(hide, HIDE_DELAY_MS);
  }

  function onFocus(event) {
    const anchor = event.currentTarget;
    window.clearTimeout(hideTimer);
    window.clearTimeout(showTimer);
    showTimer = window.setTimeout(() => show(anchor), SHOW_DELAY_MS);
  }

  function onBlur() {
    window.clearTimeout(showTimer);
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(hide, HIDE_DELAY_MS);
  }

  function onClick(event) {
    // A tap on a touch device is the only reliable way to read the hint.
    if (event.pointerType && event.pointerType !== "touch") return;
    const anchor = event.currentTarget;
    if (currentAnchor === anchor) {
      hide();
      return;
    }
    show(anchor);
  }

  function bind(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-padiem-tooltip]").forEach((anchor) => {
      if (anchor.dataset.padiemTooltipBound === "true") return;
      anchor.dataset.padiemTooltipBound = "true";
      anchor.addEventListener("pointerenter", onEnter);
      anchor.addEventListener("pointerleave", onLeave);
      anchor.addEventListener("focus", onFocus);
      anchor.addEventListener("blur", onBlur);
      anchor.addEventListener("click", onClick);
    });
  }

  function unbind(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-padiem-tooltip]").forEach(detach);
  }

  /* Replace the native popup for one anchor without losing the accessible
   * name: the label keeps `aria-label` and moves to the shared chip. */
  function label(anchor, text) {
    if (!anchor) return;
    const value = typeof text === "string" ? text : "";
    if (!value) {
      anchor.removeAttribute("data-padiem-tooltip");
      return;
    }
    anchor.setAttribute("data-padiem-tooltip", value);
    anchor.removeAttribute("title");
    bind(anchor.parentNode || document);
  }

  window.PadiemSharedTooltip = Object.freeze({
    bind,
    unbind,
    label,
    hide,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      ensureDismissListeners();
      bind(document);
    });
  } else {
    ensureDismissListeners();
    bind(document);
  }
})();
