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
  // API names reserved for their actual owner, with lazy pre-registration reads.
  const DEFERRED_API_NAMES = {
    core: ["uiT", "clawT", "mappedUiError", "idleNote", "setNote"],
    nav: ["setNavActive"],
    sidebar: ["closeSidebar"],
    clawStatus: ["clearClawWait", "clearClawRecovery", "setClawAreaState", "setClawButtonsBusy", "setClawStatus"],
    conversation: ["approvedMemoryErrorMessage", "safeLocalUiMessage", "failureCodeNote", "attachmentCopy", "renderStreamError", "renderWebGroundingNotice", "resetConversationView", "revealErrorState", "updateComposer"],
    clawRun: ["downloadClawArtifact", "renderClawApprovalControls"],
    auth: ["authMethodEnabled", "closeProfilePanel", "loadAuthStatus", "reviewedGoogleAuthorizationUrl"],
    loginDialog: ["closeAuthDialog", "openAuthDialog", "setAuthFormError", "syncAuthDialogMethods"],
    settings: ["closeSettings", "selectedProductTier"],
    project: ["loadProjects", "renderProjectState"],
    history: ["loadRecentConversations"],
    runHistory: ["syncClawRunHistoryVisibility"],
  };
  const ACCESSOR_SHADOW_ALLOWLIST = new Set(Object.values(DEFERRED_API_NAMES).flat());
  window.PadiemChatAppContext = {
    create(shared, owners = {}) {
      const registered = new Map();
      const providedNames = new Set();
      const deferred = Object.create(shared || null);
      const reserved = new Map();
      for (const [owner, resolve] of Object.entries(owners)) {
        for (const key of DEFERRED_API_NAMES[owner]) {
          if (shared && Object.prototype.hasOwnProperty.call(shared, key)) {
            throw new Error("PadiemChatAppContext: name collides with a shared accessor: " + key);
          }
          reserved.set(key, owner);
          Object.defineProperty(deferred, key, {
            get() { return resolve()[key]; }, enumerable: true, configurable: true,
          });
        }
      }
      const context = Object.create(reserved.size ? deferred : (shared || null));
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
          if (reserved.has(key) && reserved.get(key) !== name) {
            throw new Error("PadiemChatAppContext: duplicate name: " + key);
          }
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
