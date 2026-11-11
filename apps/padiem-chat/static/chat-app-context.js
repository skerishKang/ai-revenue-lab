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
  window.PadiemChatAppContext = {
    create(shared) {
      const registered = new Map();
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
          if (key in context) {
            throw new Error("PadiemChatAppContext: duplicate name: " + key);
          }
          context[key] = piece[key];
        }
        return piece;
      };
      return context;
    },
  };
})();
