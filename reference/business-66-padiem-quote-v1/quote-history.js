/* B66 · Quote Beta — browser-local recent quotation history.
   Stores bounded QuoteDraft snapshots only. Monetary totals are always derived by QuoteCore. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-core.js"));
  } else {
    root.QuoteHistory = factory(root.QuoteCore);
  }
})(typeof self !== "undefined" ? self : this, function (Core) {
  "use strict";

  if (!Core) throw new Error("QuoteCore is required");

  var HISTORY_SCHEMA_VERSION = 1;
  var HISTORY_STORAGE_KEY = "quoteBeta.history.v1";
  var MAX_HISTORY = 20;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalizeEnvelope(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { schemaVersion: HISTORY_SCHEMA_VERSION, entries: [] };
    }
    if (raw.schemaVersion !== HISTORY_SCHEMA_VERSION || !Array.isArray(raw.entries)) {
      return { schemaVersion: HISTORY_SCHEMA_VERSION, entries: [] };
    }

    var entries = [];
    raw.entries.slice(0, MAX_HISTORY).forEach(function (entry) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) return;
      if (typeof entry.id !== "string" || !entry.id.trim()) return;
      if (typeof entry.savedAt !== "string" || !entry.savedAt.trim()) return;
      var draft = Core.normalizeDraft(entry.draft);
      if (!draft) return;
      entries.push({
        id: entry.id.trim().slice(0, 120),
        savedAt: entry.savedAt.trim().slice(0, 80),
        draft: draft
      });
    });

    return { schemaVersion: HISTORY_SCHEMA_VERSION, entries: entries };
  }

  function makeId(now) {
    var stamp = String(now || new Date().toISOString()).replace(/[^0-9]/g, "").slice(0, 17);
    var suffix = Math.random().toString(36).slice(2, 8);
    return "quote-" + stamp + "-" + suffix;
  }

  function createEntry(draft, options) {
    var normalized = Core.normalizeDraft(draft);
    if (!normalized) return null;
    var opts = options || {};
    var savedAt = typeof opts.savedAt === "string" && opts.savedAt.trim()
      ? opts.savedAt.trim()
      : new Date().toISOString();
    var id = typeof opts.id === "string" && opts.id.trim()
      ? opts.id.trim()
      : makeId(savedAt);
    return {
      id: id.slice(0, 120),
      savedAt: savedAt.slice(0, 80),
      draft: clone(normalized)
    };
  }

  function addEntry(rawEnvelope, draft, options) {
    var envelope = normalizeEnvelope(rawEnvelope);
    var entry = createEntry(draft, options);
    if (!entry) return envelope;

    envelope.entries = envelope.entries.filter(function (existing) {
      return existing.id !== entry.id;
    });
    envelope.entries.unshift(entry);
    envelope.entries = envelope.entries.slice(0, MAX_HISTORY);
    return envelope;
  }

  function deleteEntry(rawEnvelope, id) {
    var envelope = normalizeEnvelope(rawEnvelope);
    envelope.entries = envelope.entries.filter(function (entry) {
      return entry.id !== id;
    });
    return envelope;
  }

  function getEntry(rawEnvelope, id) {
    var envelope = normalizeEnvelope(rawEnvelope);
    return envelope.entries.find(function (entry) { return entry.id === id; }) || null;
  }

  function listMetadata(rawEnvelope) {
    return normalizeEnvelope(rawEnvelope).entries.map(function (entry) {
      var totals = Core.computeTotals(entry.draft.items, entry.draft.tax.mode);
      return {
        id: entry.id,
        savedAt: entry.savedAt,
        recipientCompany: entry.draft.recipient.company,
        recipientPerson: entry.draft.recipient.person,
        quoteNo: entry.draft.meta.quoteNo,
        issueDate: entry.draft.meta.issueDate,
        itemCount: entry.draft.items.length,
        grand: totals.grand
      };
    });
  }

  function freshQuoteNo(now) {
    var dt = now instanceof Date ? now : new Date();
    var date = Core.isoFormat(dt).replace(/-/g, "");
    var time = String(dt.getHours()).padStart(2, "0") +
      String(dt.getMinutes()).padStart(2, "0") +
      String(dt.getSeconds()).padStart(2, "0") +
      String(dt.getMilliseconds()).padStart(3, "0");
    return "PQ-" + date + "-" + time;
  }

  function copyAsNew(entry, options) {
    if (!entry || typeof entry !== "object") return null;
    var source = Core.normalizeDraft(entry.draft);
    if (!source) return null;

    var opts = options || {};
    var now = opts.now instanceof Date ? opts.now : new Date();
    var fresh = Core.createDefaultDraft();
    fresh.meta.quoteNo = freshQuoteNo(now);
    fresh.meta.issueDate = Core.isoFormat(now);
    fresh.meta.validDays = source.meta.validDays;
    fresh.meta.source = "history-copy";
    fresh.sender = clone(source.sender);
    fresh.recipient = clone(source.recipient);
    fresh.items = source.items.map(function (item, index) {
      return {
        id: "item-" + (index + 1),
        name: item.name,
        qty: item.qty,
        unitPrice: item.unitPrice
      };
    });
    fresh.tax = clone(source.tax);
    fresh.memo = source.memo;
    return Core.normalizeDraft(fresh);
  }

  function isMeaningfulDraft(draft) {
    var normalized = Core.normalizeDraft(draft);
    if (!normalized) return false;
    var base = Core.createDefaultDraft();

    if (normalized.meta.source !== "manual") return true;
    if (normalized.meta.quoteNo !== base.meta.quoteNo) return true;
    if (normalized.meta.issueDate !== base.meta.issueDate) return true;
    if (normalized.meta.validDays !== base.meta.validDays) return true;
    if (JSON.stringify(normalized.sender) !== JSON.stringify(base.sender)) return true;
    if (JSON.stringify(normalized.recipient) !== JSON.stringify(base.recipient)) return true;
    if (JSON.stringify(normalized.items) !== JSON.stringify(base.items)) return true;
    if (normalized.tax.mode !== base.tax.mode) return true;
    if (normalized.memo !== base.memo) return true;
    return false;
  }

  return {
    HISTORY_SCHEMA_VERSION: HISTORY_SCHEMA_VERSION,
    HISTORY_STORAGE_KEY: HISTORY_STORAGE_KEY,
    MAX_HISTORY: MAX_HISTORY,
    normalizeEnvelope: normalizeEnvelope,
    createEntry: createEntry,
    addEntry: addEntry,
    deleteEntry: deleteEntry,
    getEntry: getEntry,
    listMetadata: listMetadata,
    freshQuoteNo: freshQuoteNo,
    copyAsNew: copyAsNew,
    isMeaningfulDraft: isMeaningfulDraft
  };
});
