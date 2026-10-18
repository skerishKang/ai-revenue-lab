/* Canonical PADIEM Chat / Claw / B66 conversation scroll follow behavior.
 * UI behavior only. Each product owns its message rendering, authenticated
 * send, and product-specific scroll containers.
 * Generated static copies MUST come from this file, never manual edits.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) {
    root.SharedConversationScroll = api;
    root.PadiemConversationScroll = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : null, function () {
  "use strict";
  const VERSION = "shared-scroll-v1";
  const NEAR_BOTTOM_PX = 120;
  function isNearBottom(container, thresholdPx = NEAR_BOTTOM_PX) {
    if (!container || typeof container !== "object") return true;
    const height = Number(container.scrollHeight) || 0;
    const top = Number(container.scrollTop) || 0;
    const visible = Number(container.clientHeight) || 0;
    return (height - top - visible) < thresholdPx;
  }
  function followToBottom(container) {
    if (!container || typeof container !== "object") return false;
    const height = Number(container.scrollHeight);
    if (!Number.isFinite(height)) return false;
    container.scrollTop = height;
    return true;
  }
  return Object.freeze({ VERSION, NEAR_BOTTOM_PX, isNearBottom, followToBottom });
});
