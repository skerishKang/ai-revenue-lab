// R5 B1 - the shared app context (pilot): the module registry (rule (d)) and
// the one-flat namespace the pilot zones read shared state through (rule (c)).
//
// B1 pilot scope: the context owns the two DOM refs shared across the two
// automation modules (clawAutomation, clawAutomationList) and looks them up at
// create() time — the same script tick app.js's declaration block used to run.
// app.js still owns authState/shell/clawWorkspace and the shared functions
// (uiT, setNavActive, closeSidebar, clearClawWait, syncClawRunHistoryVisibility)
// until R5 B6; it mounts them as live accessors, so a value changed before the
// first read is still observed (same semantics as the old deps getters).
// Registering the same module or the same name twice throws (one flat
// namespace, conflicts surface immediately).
(() => {
  "use strict";
  // B6 review: a module API key that shadows a shared-state accessor is only
  // tolerable when the module is the real owner of the value, so reading the
  // module value can never diverge from app.js's own state. Only the names
  // below may shadow an accessor; any other collision is a hard error.
  const ACCESSOR_SHADOW_ALLOWLIST = new Set([
    // syncClawRunHistoryVisibility — runHistory is the owner: app.js's accessor
    // and its one-line forwarder both end at
    // runHistory.syncClawRunHistoryVisibility, which closes over the module's
    // own state and reads no `this`, so either path behaves identically.
    "syncClawRunHistoryVisibility",
    // closeSidebar — B7 (CTO-approved): the sidebar module is the owner —
    // app.js's accessor and its one-line forwarder both end at
    // sidebarModule().closeSidebar, which closes over the module's own state
    // and reads no `this`, so either path behaves identically.
    // B7 임시 — 마지막 단계에서 app.js 접근자 제거 시 목록에서 뺀다.
    "closeSidebar",
    // selectedProductTier / closeSettings — B7 (CTO-approved 2026-11-18, 3차 +
    // 상시 승인 규칙): the settings module is the owner — app.js's accessors
    // and one-line forwarders both end at the same settings-module methods,
    // which close over the module's own state and read no `this`.
    // B7 임시 — 마지막 단계에서 app.js 접근자 제거 시 목록에서 뺀다.
    "selectedProductTier",
    "closeSettings",
    // setNavActive — B7 (CTO-approved 2026-11-18, 6차 + 상시 승인 규칙):
    // app.js accessor and every call site delegate to the nav module's own
    // setNavActive at the original factory position; the method reads no
    // `this`, so either path behaves identically.
    // B7 임시 — 마지막 단계에서 app.js 접근자 제거 시 목록에서 뺀다.
    "setNavActive",
  ]);
  window.PadiemChatAppContext = {
    create(shared) {
      const registered = new Map();
      const providedNames = new Set();
      const context = Object.create(shared || null);
      context.clawAutomation = document.getElementById("clawAutomation");
      context.clawAutomationList = document.getElementById("clawAutomationList");
      // R5 A2: DOM refs shared between the moved memory/run-history modules and
      // remaining app.js / chat-history-module.js.
      context.clawMemoryReview = document.getElementById("clawMemoryReview");
      context.clawRunHistory = document.getElementById("clawRunHistory");
      context.clawRunHistoryExpand = document.getElementById("clawRunHistoryExpand");
      context.provide = (name, piece) => {
        if (registered.has(name)) {
          throw new Error("PadiemChatAppContext: duplicate module registration: " + name);
        }
        registered.set(name, piece);
        for (const key of Object.keys(piece)) {
          if (providedNames.has(key)) {
            throw new Error("PadiemChatAppContext: duplicate name: " + key);
          }
          // B6 review: shadowing a shared-state accessor is reserved for the
          // allowlisted owners; a second module providing the same name, or a
          // module name colliding with any other accessor, is a hard error
          // instead of a silent overwrite.
          if (shared && Object.prototype.hasOwnProperty.call(shared, key)
              && !ACCESSOR_SHADOW_ALLOWLIST.has(key)) {
            throw new Error("PadiemChatAppContext: name collides with a shared accessor: " + key);
          }
          if (Object.prototype.hasOwnProperty.call(context, key)) {
            throw new Error("PadiemChatAppContext: name collides with a context-owned ref: " + key);
          }
          providedNames.add(key);
          // app.js owns shared state and exposes live accessors on the prototype
          // until B7. Only the allowlisted owner names shadow that accessor
          // (see ACCESSOR_SHADOW_ALLOWLIST); anything else errors above.
          Object.defineProperty(context, key, {
            value: piece[key], writable: true, configurable: true, enumerable: true,
          });
        }
        return piece;
      };
      return context;
    },
  };
})();
