/* B66 · Quote Beta — quote-core.js
   견적 도메인 로직 (DOM 없음 · 브라우저/Node 양쪽에서 실행).
   금액·날짜 계산의 최종 authority는 이 코드이며 AI가 아님. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.QuoteCore = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var SCHEMA_VERSION = 1;
  var DRAFT_STORAGE_KEY = "quoteBeta.draft.v1";
  var SENDER_STORAGE_KEY = "quoteBeta.sender";
  var VAT_RATE = 0.10;

  var TAX_MODES = { EXCLUSIVE: "EXCLUSIVE", INCLUSIVE: "INCLUSIVE", EXEMPT: "EXEMPT" };
  var TAX_LABELS = {
    EXCLUSIVE: "부가세 별도 (VAT 10%)",
    INCLUSIVE: "VAT 포함가",
    EXEMPT: "면세 (부가세 없음)"
  };

  /* ── money parse / format : 화면 표시(콤마)와 내부 값(숫자)을 명시적으로 분리 ── */

  function parseMoney(raw) {
    var s = String(raw == null ? "" : raw).replace(/[,\s]/g, "");
    if (s === "") return 0;
    if (!/^\d+(\.\d+)?$/.test(s)) return 0; /* 잘못된 입력은 NaN 대신 0 — 합계 오염 금지 */
    var n = Number(s);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  function parseKoreanMoney(raw) {
    var s = String(raw == null ? "" : raw)
      .trim()
      .replace(/\s+/g, "")
      .replace(/^₩/, "")
      .replace(/,/g, "");
    if (s.endsWith("원")) s = s.slice(0, -1);
    if (!s) return null;

    var match = /^(\d+(?:\.\d+)?)(억|만|천)$/.exec(s);
    if (match) {
      var unit = match[2] === "억" ? 100000000 : match[2] === "만" ? 10000 : 1000;
      var unitValue = Number(match[1]);
      if (!Number.isFinite(unitValue) || unitValue < 0) return null;
      var scaled = Math.round(unitValue * unit);
      return Number.isSafeInteger(scaled) ? scaled : null;
    }

    if (!/^\d+(?:\.\d+)?$/.test(s)) return null;
    var value = Number(s);
    if (!Number.isFinite(value) || value < 0) return null;
    var rounded = Math.round(value);
    return Number.isSafeInteger(rounded) ? rounded : null;
  }

  function formatMoney(n) {
    return new Intl.NumberFormat("ko-KR", {
      style: "currency",
      currency: "KRW",
      maximumFractionDigits: 0
    }).format(Number(n) || 0);
  }

  function formatInputNumber(n) {
    return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(Number(n) || 0);
  }

  /* ── 합계: item.amount / supply / vat / grand 는 저장값이 아니라 매번 파생 ── */

  function itemAmount(item) {
    var qty = parseMoney(item && item.qty);
    var price = parseMoney(item && item.unitPrice);
    return Math.round(qty * price);
  }

  function computeTotals(items, taxMode) {
    var amounts = (items || []).map(itemAmount);
    var subtotal = amounts.reduce(function (sum, a) { return sum + a; }, 0);
    var mode = TAX_MODES[taxMode] ? taxMode : TAX_MODES.EXCLUSIVE;
    var supply, vat, grand;
    if (mode === TAX_MODES.INCLUSIVE) {
      grand = subtotal;
      supply = Math.round(grand / 1.10);
      vat = grand - supply;
    } else if (mode === TAX_MODES.EXEMPT) {
      supply = subtotal;
      vat = 0;
      grand = supply;
    } else {
      supply = subtotal;
      vat = Math.round(subtotal * 0.10);
      grand = supply + vat;
    }
    return { amounts: amounts, subtotal: subtotal, supply: supply, vat: vat, grand: grand, mode: mode };
  }

  /* ── 날짜: 견적일 + 유효기간 → 유효일. 파싱 실패 시 null (crash 금지) ── */

  function parseISODate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) return null;
    var parts = value.trim().split("-");
    var y = Number(parts[0]);
    var m = Number(parts[1]);
    var d = Number(parts[2]);
    var dt = new Date(y, m - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null;
    return dt;
  }

  function isoFormat(dt) {
    return dt.getFullYear() + "-" +
      String(dt.getMonth() + 1).padStart(2, "0") + "-" +
      String(dt.getDate()).padStart(2, "0");
  }

  function todayISO() {
    return isoFormat(new Date());
  }

  function computeValidUntil(issueDate, validDays) {
    var start = parseISODate(issueDate);
    var days = Number(validDays);
    if (!start || !Number.isFinite(days) || days <= 0) return null;
    return isoFormat(new Date(start.getFullYear(), start.getMonth(), start.getDate() + days));
  }

  /* ── QuoteDraft: 저장/복원되는 유일한 상태 객체 ── */

  function createDefaultDraft() {
    var today = todayISO();
    return {
      schemaVersion: SCHEMA_VERSION,
      meta: {
        quoteNo: "PQ-" + today.split("-").join("") + "-001",
        issueDate: today,
        validDays: 30,
        source: "manual"
      },
      sender: {
        company: "샘플 공급사",
        rep: "대표자명",
        bizNo: "000-00-00000",
        address: "",
        phone: "000-0000-0000",
        email: "hello@example.com",
        presetId: "sample"
      },
      recipient: { company: "고객사", person: "담당자님", address: "", email: "" },
      items: [
        { id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 },
        { id: "item-2", name: "운영 지원", qty: 1, unitPrice: 300000 }
      ],
      tax: { mode: TAX_MODES.EXCLUSIVE, rate: VAT_RATE },
      memo: "견적 유효기간 내 발주 시 상기 금액을 적용합니다.\n세부 일정은 협의 후 확정합니다."
    };
  }

  function asString(v, fallback) {
    return typeof v === "string" ? v : fallback;
  }

  function asNonNegativeNumber(v, fallback) {
    var n = Number(v);
    if (!Number.isFinite(n) || n < 0) return fallback;
    return n;
  }

  /* 손상된 JSON·구버전 schema → null (앱이 기본 데모 상태로 fallback) */
  function normalizeDraft(raw) {
    try {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
      if (raw.schemaVersion !== SCHEMA_VERSION) return null;
      var base = createDefaultDraft();
      var rawItems = Array.isArray(raw.items) && raw.items.length > 0 ? raw.items : base.items;
      var items = rawItems.map(function (it, i) {
        var src = it && typeof it === "object" ? it : {};
        return {
          id: asString(src.id, "item-" + (i + 1)),
          name: asString(src.name, ""),
          qty: asNonNegativeNumber(src.qty, 1),
          unitPrice: asNonNegativeNumber(src.unitPrice, 0)
        };
      });
      var taxMode = raw.tax && TAX_MODES[raw.tax.mode] ? raw.tax.mode : base.tax.mode;
      return {
        schemaVersion: SCHEMA_VERSION,
        meta: {
          quoteNo: asString(raw.meta && raw.meta.quoteNo, base.meta.quoteNo),
          issueDate: asString(raw.meta && raw.meta.issueDate, base.meta.issueDate),
          validDays: asNonNegativeNumber(raw.meta && raw.meta.validDays, base.meta.validDays),
          source: asString(raw.meta && raw.meta.source, "manual")
        },
        sender: {
          company: asString(raw.sender && raw.sender.company, base.sender.company),
          rep: asString(raw.sender && raw.sender.rep, base.sender.rep),
          bizNo: asString(raw.sender && raw.sender.bizNo, base.sender.bizNo),
          address: asString(raw.sender && raw.sender.address, ""),
          phone: asString(raw.sender && raw.sender.phone, base.sender.phone),
          email: asString(raw.sender && raw.sender.email, base.sender.email),
          presetId: asString(raw.sender && raw.sender.presetId, base.sender.presetId)
        },
        recipient: {
          company: asString(raw.recipient && raw.recipient.company, base.recipient.company),
          person: asString(raw.recipient && raw.recipient.person, base.recipient.person),
          address: asString(raw.recipient && raw.recipient.address, ""),
          email: asString(raw.recipient && raw.recipient.email, "")
        },
        items: items,
        tax: {
          mode: taxMode,
          rate: asNonNegativeNumber(raw.tax && raw.tax.rate, VAT_RATE)
        },
        memo: asString(raw.memo, base.memo)
      };
    } catch (err) {
      return null;
    }
  }

  function printReadiness(rawDraft) {
    var normalized = normalizeDraft(rawDraft);
    if (!normalized) {
      return { ready: false, missing: ["invalid_draft"] };
    }

    var missing = [];
    if (!String(normalized.meta.quoteNo || "").trim()) missing.push("quote_no");
    if (!parseISODate(normalized.meta.issueDate)) missing.push("issue_date");
    if (!String(normalized.sender.company || "").trim()) missing.push("sender_company");
    if (
      !String(normalized.recipient.company || "").trim() &&
      !String(normalized.recipient.person || "").trim()
    ) {
      missing.push("recipient");
    }

    var hasNamedItem = normalized.items.some(function (item) {
      return String(item.name || "").trim() && parseMoney(item.qty) > 0;
    });
    if (!hasNamedItem) missing.push("items");

    return { ready: missing.length === 0, missing: missing };
  }

  function createBlankQuoteDraft(currentDraft, options) {
    var current = normalizeDraft(currentDraft) || createDefaultDraft();
    var defaults = createDefaultDraft();
    var opts = options || {};
    var issueDate = typeof opts.issueDate === "string" && parseISODate(opts.issueDate)
      ? opts.issueDate
      : todayISO();
    var quoteNo = typeof opts.quoteNo === "string" && opts.quoteNo.trim()
      ? opts.quoteNo.trim()
      : defaults.meta.quoteNo;
    var source = typeof opts.source === "string" && opts.source.trim()
      ? opts.source.trim()
      : "manual";

    return normalizeDraft({
      schemaVersion: SCHEMA_VERSION,
      meta: {
        quoteNo: quoteNo,
        issueDate: issueDate,
        validDays: current.meta.validDays > 0 ? current.meta.validDays : defaults.meta.validDays,
        source: source
      },
      sender: {
        company: current.sender.company,
        rep: current.sender.rep,
        bizNo: current.sender.bizNo,
        address: current.sender.address,
        phone: current.sender.phone,
        email: current.sender.email,
        presetId: current.sender.presetId
      },
      recipient: { company: "", person: "", address: "", email: "" },
      items: [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }],
      tax: { mode: TAX_MODES.EXCLUSIVE, rate: VAT_RATE },
      memo: defaults.memo
    });
  }

  return {
    SCHEMA_VERSION: SCHEMA_VERSION,
    DRAFT_STORAGE_KEY: DRAFT_STORAGE_KEY,
    SENDER_STORAGE_KEY: SENDER_STORAGE_KEY,
    VAT_RATE: VAT_RATE,
    TAX_MODES: TAX_MODES,
    TAX_LABELS: TAX_LABELS,
    parseMoney: parseMoney,
    parseKoreanMoney: parseKoreanMoney,
    formatMoney: formatMoney,
    formatInputNumber: formatInputNumber,
    itemAmount: itemAmount,
    computeTotals: computeTotals,
    parseISODate: parseISODate,
    isoFormat: isoFormat,
    todayISO: todayISO,
    computeValidUntil: computeValidUntil,
    printReadiness: printReadiness,
    createDefaultDraft: createDefaultDraft,
    createBlankQuoteDraft: createBlankQuoteDraft,
    normalizeDraft: normalizeDraft
  };
});
