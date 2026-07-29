/*
 * AI Revenue Lab — Business Authority Summary
 *
 * Generates classification counts from the runtime Business
 * records. Used for both the UI and the audit document.
 *
 * This is a derived view; the single source of truth remains
 * businesses.js.
 *
 * Must be loaded after businesses.js.
 */

window.ARL_SUMMARY = (function () {
  "use strict";

  var VOCAB = window.ARL_VOCABULARY;
  var businesses = window.ARL_BUSINESSES;

  if (!VOCAB || !Array.isArray(businesses)) {
    return null;
  }

  var summary = VOCAB.generateSummary(businesses);
  return summary;
})();
