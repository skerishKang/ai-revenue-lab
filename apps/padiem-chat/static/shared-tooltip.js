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

  function place(anchor) {
    const node = ensureBubble();
    const rect = anchor.getBoundingClientRect();
    node.style.visibility = "hidden";
    node.style.left = "0px";
    node.style.top = "0px";
    const size = node.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth;
    let left = rect.left + (rect.width / 2) - (size.width / 2);
    left = Math.max(6, Math.min(left, viewportWidth - size.width - 6));
    let top = rect.top - size.height - OFFSET_PX;
    if (top < 6) {
      top = rect.bottom + OFFSET_PX;
    }
    node.style.left = Math.round(left) + "px";
    node.style.top = Math.round(top) + "px";
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
    if (!bubble) return;
    bubble.dataset.padiemTooltipState = "hidden";
    bubble.setAttribute("aria-hidden", "true");
    if (currentAnchor) {
      currentAnchor.removeAttribute("aria-describedby");
      currentAnchor = null;
    }
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
    document.addEventListener("DOMContentLoaded", () => bind(document));
  } else {
    bind(document);
  }
})();
