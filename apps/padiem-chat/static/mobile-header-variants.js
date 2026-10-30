/* #5805 — opt-in phone header variants for the owner's design comparison.
 * The merged glass menu (interaction-polish.css) stays the production
 * default; this file only acts on the explicit ?mobileHeader= parameter. It
 * writes one data attribute and, for the collapse variant, mirrors the
 * primary surface scroll position onto .app-shell[data-header-collapsed].
 * No routing, no network, no sidebar behavior, no state without the
 * parameter. */
(() => {
  "use strict";

  const variant = new URLSearchParams(window.location.search).get("mobileHeader");
  if (variant !== "floating" && variant !== "collapse") return;

  const root = document.documentElement;
  root.dataset.mobileHeader = variant;
  if (variant !== "collapse") return;

  /* The row shrinks while a primary surface is scrolled away from the top
   * and comes back at the top. Inner scrollers (code blocks, chip rows) must
   * not trigger it, so the check stays on the column-level surfaces, and a
   * hidden view (e.g. the Claw inbox behind the conversation) keeps a stale
   * offset that must not count. */
  const SCROLL_SURFACES = ".conversation, .claw-workspace, .claw-inbox";
  const COLLAPSE_THRESHOLD = 24;
  let scheduled = false;

  const sync = () => {
    scheduled = false;
    const shell = document.querySelector(".app-shell");
    if (!shell) return;
    let away = false;
    const docScroller = document.scrollingElement;
    if (docScroller && docScroller.scrollTop > COLLAPSE_THRESHOLD) away = true;
    for (const surface of shell.querySelectorAll(SCROLL_SURFACES)) {
      if (surface.offsetParent === null) continue;
      if (surface.scrollTop > COLLAPSE_THRESHOLD) {
        away = true;
        break;
      }
    }
    shell.toggleAttribute("data-header-collapsed", away);
  };

  document.addEventListener("scroll", () => {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(sync);
  }, { capture: true, passive: true });

  sync();
})();
