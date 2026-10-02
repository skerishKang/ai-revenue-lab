/* B66 · Quote Beta — model-independent extraction-result contract.
   Provider/model output is untrusted input. This module validates extraction facts only.
   Money totals, VAT amounts and valid-until dates remain QuoteCore authority. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.QuoteExtraction = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MAX_ITEMS = 100;
  var MAX_TEXT = 2000;
  var MAX_MEMO = 8000;
  var MAX_FILENAME = 255;
  var MAX_EVIDENCE = 200;
  var MAX_EVIDENCE_SNIPPET = 1000;
  var MAX_WARNINGS = 50;

  var SOURCE_KINDS = Object.freeze({
    text: true,
    native_document: true,
    image: true,
    scanned_pdf: true
  });

  var TAX_MODES = Object.freeze({
    EXCLUSIVE: true,
    INCLUSIVE: true,
    EXEMPT: true
  });

  function fail(code) {
    var err = new Error(code);
    err.code = code;
    throw err;
  }

  function isObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function optionalText(value, maxLength, code) {
    if (value == null) return null;
    if (typeof value !== "string") fail(code || "invalid_text");
    var text = value.trim();
    if (text.length > maxLength) fail(code || "text_too_long");
    return text === "" ? null : text;
  }

  function optionalMoney(value, code) {
    if (value == null || value === "") return null;
    if (typeof value === "number") {
      if (!Number.isFinite(value) || value < 0) fail(code || "invalid_money");
      return value;
    }
    if (typeof value !== "string") fail(code || "invalid_money");
    var compact = value.replace(/[,\s]/g, "");
    if (!/^\d+(\.\d+)?$/.test(compact)) fail(code || "invalid_money");
    var number = Number(compact);
    if (!Number.isFinite(number) || number < 0) fail(code || "invalid_money");
    return number;
  }

  function optionalPositiveInteger(value, code) {
    if (value == null || value === "") return null;
    var number = typeof value === "string" && /^\d+$/.test(value.trim())
      ? Number(value.trim())
      : value;
    if (!Number.isInteger(number) || number <= 0) fail(code || "invalid_positive_integer");
    return number;
  }

  function optionalISODate(value) {
    var text = optionalText(value, 10, "invalid_issue_date");
    if (text == null) return null;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) fail("invalid_issue_date");
    var parts = text.split("-").map(Number);
    var date = new Date(parts[0], parts[1] - 1, parts[2]);
    if (
      date.getFullYear() !== parts[0] ||
      date.getMonth() !== parts[1] - 1 ||
      date.getDate() !== parts[2]
    ) {
      fail("invalid_issue_date");
    }
    return text;
  }

  function normalizeParty(raw, fields, prefix) {
    if (raw == null) raw = {};
    if (!isObject(raw)) fail("invalid_" + prefix);
    var result = {};
    fields.forEach(function (field) {
      result[field] = optionalText(raw[field], MAX_TEXT, "invalid_" + prefix + "_" + field);
    });
    return result;
  }

  function normalizeItems(raw) {
    if (raw == null) return [];
    if (!Array.isArray(raw)) fail("invalid_items");
    if (raw.length > MAX_ITEMS) fail("too_many_items");

    return raw.map(function (item, index) {
      if (!isObject(item)) fail("invalid_item_" + index);
      return {
        name: optionalText(item.name, MAX_TEXT, "invalid_item_name"),
        spec: optionalText(item.spec, MAX_TEXT, "invalid_item_spec"),
        unit: optionalText(item.unit, 80, "invalid_item_unit"),
        qty: optionalMoney(item.qty, "invalid_item_qty"),
        unitPrice: optionalMoney(item.unitPrice, "invalid_item_unit_price"),
        note: optionalText(item.note, MAX_TEXT, "invalid_item_note")
      };
    });
  }

  function normalizeEvidence(raw) {
    if (raw == null) return [];
    if (!Array.isArray(raw)) fail("invalid_evidence");
    if (raw.length > MAX_EVIDENCE) fail("too_much_evidence");

    return raw.map(function (entry, index) {
      if (!isObject(entry)) fail("invalid_evidence_" + index);
      var field = optionalText(entry.field, MAX_TEXT, "invalid_evidence_field");
      if (!field) fail("invalid_evidence_field");

      var page = entry.page == null ? null : optionalPositiveInteger(entry.page, "invalid_evidence_page");
      var snippet = optionalText(entry.snippet, MAX_EVIDENCE_SNIPPET, "invalid_evidence_snippet");
      var confidence = null;
      if (entry.confidence != null) {
        if (
          typeof entry.confidence !== "number" ||
          !Number.isFinite(entry.confidence) ||
          entry.confidence < 0 ||
          entry.confidence > 1
        ) {
          fail("invalid_evidence_confidence");
        }
        confidence = entry.confidence;
      }

      return {
        field: field,
        page: page,
        snippet: snippet,
        confidence: confidence
      };
    });
  }

  function normalizeWarnings(raw) {
    if (raw == null) return [];
    if (!Array.isArray(raw)) fail("invalid_warnings");
    if (raw.length > MAX_WARNINGS) fail("too_many_warnings");
    return raw.map(function (warning) {
      var text = optionalText(warning, MAX_TEXT, "invalid_warning");
      if (!text) fail("invalid_warning");
      return text;
    });
  }

  function normalizeExtraction(raw) {
    try {
      if (!isObject(raw)) fail("invalid_extraction");

      if (!isObject(raw.source)) fail("invalid_source");
      var kind = optionalText(raw.source.kind, 64, "invalid_source_kind");
      if (!kind || !SOURCE_KINDS[kind]) fail("unsupported_source_kind");
      var filename = optionalText(raw.source.filename, MAX_FILENAME, "invalid_source_filename");

      var sender = normalizeParty(
        raw.sender,
        ["company", "rep", "bizNo", "address", "phone", "email"],
        "sender"
      );
      var recipient = normalizeParty(
        raw.recipient,
        ["company", "person", "address", "email"],
        "recipient"
      );

      var quoteRaw = raw.quote == null ? {} : raw.quote;
      if (!isObject(quoteRaw)) fail("invalid_quote");
      var quote = {
        quoteNo: optionalText(quoteRaw.quoteNo, MAX_TEXT, "invalid_quote_number"),
        issueDate: optionalISODate(quoteRaw.issueDate),
        validDays: optionalPositiveInteger(quoteRaw.validDays, "invalid_valid_days"),
        projectName: optionalText(quoteRaw.projectName, MAX_TEXT, "invalid_project_name")
      };

      var warnings = normalizeWarnings(raw.warnings);
      var taxMode = null;
      if (raw.tax != null) {
        if (!isObject(raw.tax)) fail("invalid_tax");
        if (raw.tax.mode != null && raw.tax.mode !== "") {
          if (typeof raw.tax.mode !== "string") fail("invalid_tax_mode");
          if (TAX_MODES[raw.tax.mode]) {
            taxMode = raw.tax.mode;
          } else {
            warnings.push("unknown_tax_mode");
          }
        }
      }

      var result = {
        source: {
          kind: kind,
          filename: filename
        },
        sender: sender,
        recipient: recipient,
        quote: quote,
        items: normalizeItems(raw.items),
        tax: { mode: taxMode },
        memo: optionalText(raw.memo, MAX_MEMO, "invalid_memo"),
        evidence: normalizeEvidence(raw.evidence),
        warnings: warnings
      };

      return { ok: true, value: result };
    } catch (err) {
      return {
        ok: false,
        error: err && typeof err.code === "string" ? err.code : "invalid_extraction"
      };
    }
  }


  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function assignIfPresent(target, key, value) {
    if (value !== null && value !== undefined) target[key] = value;
  }

  function hasPartyValue(party) {
    return Object.keys(party || {}).some(function (key) {
      return party[key] !== null && party[key] !== undefined;
    });
  }

  function buildDraftCandidate(currentDraft, rawExtraction) {
    var normalized = normalizeExtraction(rawExtraction);
    if (!normalized.ok) return normalized;
    if (!isObject(currentDraft)) return { ok: false, error: "invalid_current_draft" };

    var candidate;
    try {
      candidate = cloneJson(currentDraft);
    } catch (err) {
      return { ok: false, error: "invalid_current_draft" };
    }

    if (
      !isObject(candidate.meta) ||
      !isObject(candidate.sender) ||
      !isObject(candidate.recipient) ||
      !isObject(candidate.tax) ||
      !Array.isArray(candidate.items)
    ) {
      return { ok: false, error: "invalid_current_draft" };
    }

    var extracted = normalized.value;
    candidate.meta.source = "extraction:" + extracted.source.kind;
    assignIfPresent(candidate.meta, "quoteNo", extracted.quote.quoteNo);
    assignIfPresent(candidate.meta, "issueDate", extracted.quote.issueDate);
    assignIfPresent(candidate.meta, "validDays", extracted.quote.validDays);
    assignIfPresent(candidate.meta, "projectName", extracted.quote.projectName);

    ["company", "rep", "bizNo", "address", "phone", "email"].forEach(function (key) {
      assignIfPresent(candidate.sender, key, extracted.sender[key]);
    });
    if (hasPartyValue(extracted.sender)) candidate.sender.presetId = "custom";

    ["company", "person", "address", "email"].forEach(function (key) {
      assignIfPresent(candidate.recipient, key, extracted.recipient[key]);
    });

    if (extracted.items.length > 0) {
      candidate.items = extracted.items.map(function (item, index) {
        var mapped = {
          id: "extracted-item-" + (index + 1),
          name: item.name == null ? "" : item.name,
          qty: item.qty == null ? 0 : item.qty,
          unitPrice: item.unitPrice == null ? 0 : item.unitPrice
        };
        assignIfPresent(mapped, "spec", item.spec);
        assignIfPresent(mapped, "unit", item.unit);
        assignIfPresent(mapped, "note", item.note);
        return mapped;
      });
    }

    if (extracted.tax.mode !== null) candidate.tax.mode = extracted.tax.mode;
    if (extracted.memo !== null) candidate.memo = extracted.memo;

    return {
      ok: true,
      value: {
        draft: candidate,
        review: {
          source: cloneJson(extracted.source),
          evidence: cloneJson(extracted.evidence),
          warnings: cloneJson(extracted.warnings)
        }
      }
    };
  }

  return {
    MAX_ITEMS: MAX_ITEMS,
    MAX_TEXT: MAX_TEXT,
    MAX_MEMO: MAX_MEMO,
    MAX_EVIDENCE: MAX_EVIDENCE,
    SOURCE_KINDS: SOURCE_KINDS,
    TAX_MODES: TAX_MODES,
    normalizeExtraction: normalizeExtraction,
    buildDraftCandidate: buildDraftCandidate
  };
});