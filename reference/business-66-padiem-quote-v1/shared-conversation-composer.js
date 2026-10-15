/* Canonical PADIEM Chat / Claw / B66 composer behavior.
 * UI behavior only. Each product owns its authenticated send, model,
 * attachment, microphone, account and quote/PC execution decisions.
 * Generated static copies MUST come from this file, never manual edits.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.PadiemConversationComposer = api;
})(typeof globalThis !== "undefined" ? globalThis : null, function () {
  "use strict";
  const VERSION = "shared-composer-v1";
  function createCompositionGuard() {
    let composing = false;
    return Object.freeze({
      start() { composing = true; },
      update() { composing = true; },
      end() { composing = false; },
      reset() { composing = false; },
      isComposing() { return composing; },
    });
  }
  function shouldSubmitOnEnter(event, guard) {
    if (!event || typeof event !== "object" || Array.isArray(event)) return false;
    if (event.key !== "Enter" || event.shiftKey === true) return false;
    if (event.altKey === true || event.ctrlKey === true || event.metaKey === true) return false;
    if (event.isComposing === true || event.keyCode === 229) return false;
    if (guard && typeof guard.isComposing === "function" && guard.isComposing()) return false;
    return true;
  }
  function resizeTextarea(textarea, options = {}) {
    if (!textarea || !textarea.style) return 0;
    const minimum = Number.isFinite(options.minHeight) ? Math.max(0, options.minHeight) : 0;
    const maximum = Number.isFinite(options.maxHeight) ? Math.max(minimum, options.maxHeight) : 180;
    textarea.style.height = "auto";
    const desiredHeight = Math.max(minimum, Number(textarea.scrollHeight) || minimum);
    const finalHeight = Math.min(maximum, desiredHeight);
    textarea.style.height = finalHeight + "px";
    textarea.style.overflowY = desiredHeight > maximum ? "auto" : "hidden";
    return finalHeight;
  }
  return Object.freeze({ VERSION, createCompositionGuard, shouldSubmitOnEnter, resizeTextarea });
});
