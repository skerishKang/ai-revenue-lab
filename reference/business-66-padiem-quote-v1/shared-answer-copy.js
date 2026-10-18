/* Canonical PADIEM Chat / Claw / B66 answer-copy clipboard behavior.
 * UI behavior only. Each product owns its action bar, labels, feedback and
 * which messages are copyable.
 * Generated static copies MUST come from this file, never manual edits.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) {
    // Product-neutral alias for B66 quote UI domain integrity checks.
    root.SharedAnswerCopy = api;
    root.PadiemAnswerCopy = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : null, function () {
  "use strict";
  const VERSION = "shared-answer-copy-v1";
  function legacyCopy(text) {
    const doc = typeof document !== "undefined" ? document : null;
    if (!doc || typeof doc.execCommand !== "function") return false;
    try {
      const field = doc.createElement("textarea");
      field.value = text;
      doc.body.appendChild(field);
      field.select();
      const ok = doc.execCommand("copy");
      field.remove();
      return ok === true;
    } catch (_) {
      return false;
    }
  }
  /* Resolves true only when the text actually reached the clipboard; never
   * throws, so a product can render truthful success/failure feedback. */
  function copyText(text) {
    const value = String(text == null ? "" : text);
    const nav = typeof navigator !== "undefined" ? navigator : null;
    if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
      return Promise.resolve(nav.clipboard.writeText(value)).then(() => true, () => false);
    }
    return Promise.resolve(legacyCopy(value));
  }
  return Object.freeze({ VERSION, copyText });
});
