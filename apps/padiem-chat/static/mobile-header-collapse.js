/* #5805 — the phone header row collapses while a primary surface scrolls.
 *
 * CTO decision on PR #6274 (2026-10-30): this is the default behavior below
 * 920px, no opt-in parameter. The surface CSS lives in
 * mobile-header-collapse.css; this file only mirrors the scroll state of the
 * primary surfaces onto .app-shell[data-header-collapsed]. No routing, no
 * network, no sidebar behavior.
 */
(() => {
  "use strict";

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
