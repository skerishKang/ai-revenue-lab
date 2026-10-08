/* B66 · Quote Beta — canonical server quote-history client (#3405 Slice B).
   Signed-in 최근 견적 authority 는 서버 quote-history API 다(#3405 Slice A).
   이 모듈은:
   - QuoteDraft 를 서버 정규화 스냅샷(schema "b66.quote-draft.v1")으로, 그 다시
     QuoteDraft 입력으로 변환한다(역변환은 항상 QuoteCore.normalizeDraft 로 끝난다).
   - 금액 합계를 계산/신뢰/전송하지 않는다. stored record 는 total authority 가
     아니며, 재계산은 항상 QuoteCore 만 한다(totals_authority=quote-core).
   - owner/workspace 를 보내거나 읽지 않는다. 소유권은 세션에서 서버가 도출한다.
   - 서버 실패를 localStorage 로 대체하지 않는다. 결과는 bounded code 로 돌아온다.
   No DOM. Runs in browser and Node (tests inject fetch). */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-core.js"));
  } else {
    root.B66QuoteHistoryServer = factory(root.QuoteCore);
  }
})(typeof self !== "undefined" ? self : this, function (Core) {
  "use strict";

  if (!Core) throw new Error("QuoteCore is required");

  var SNAPSHOT_SCHEMA = "b66.quote-draft.v1";
  var QUOTES_API_BASE = "/api/padiem/b66/quotes";
  var ROW_ID_PATTERN = /^b66quote_[0-9a-f]{32}$/;
  var MAX_LIST_LIMIT = 20;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function boundedText(value, maxLength) {
    if (typeof value !== "string") return "";
    var text = value.trim();
    if (!text || text.length > maxLength) return "";
    return text;
  }

  function boundedNumber(value, fallback) {
    var n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : fallback;
  }

  /* ── QuoteDraft → 서버 저장 스냅샷 ──
     서버가 수용하는 필드만 담는다. detailGroups/calculationPolicy 는 서버
     quote-history 정규화가 보존하지 않으므로 애초에 보내지 않는다(무손실
     저장이라고 주장하지 않는다). 합계 필드는 어떤 형태로도 만들지 않는다. */
  function draftToHistorySnapshot(draft) {
    var normalized = Core.normalizeDraft(draft);
    if (!normalized) return null;

    var snapshot = {
      schema: SNAPSHOT_SCHEMA,
      quotationNo: normalized.meta.quoteNo,
      issueDate: normalized.meta.issueDate,
      validityDays: normalized.meta.validDays,
      sourceKind: normalized.meta.source,
      taxMode: normalized.tax.mode,
      vatRate: normalized.tax.rate,
      recipient: {
        company: normalized.recipient.company,
        person: normalized.recipient.person,
        address: normalized.recipient.address,
        email: normalized.recipient.email
      },
      sender: {
        company: normalized.sender.company,
        rep: normalized.sender.rep,
        contactPerson: normalized.sender.contactPerson,
        bizNo: normalized.sender.bizNo,
        address: normalized.sender.address,
        phone: normalized.sender.phone,
        email: normalized.sender.email,
        presetId: normalized.sender.presetId
      },
      items: normalized.items.map(function (item) {
        var row = { name: item.name, qty: item.qty, unitPrice: item.unitPrice };
        if (item.spec) row.spec = item.spec;
        if (item.unit) row.unit = item.unit;
        if (item.note) row.note = item.note;
        return row;
      }),
      memo: normalized.memo
    };
    if (normalized.meta.projectName) snapshot.projectName = normalized.meta.projectName;
    return snapshot;
  }

  function snapshotObject(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    var out = {};
    Object.keys(value).forEach(function (key) {
      var item = value[key];
      if (item === null || typeof item === "string" || typeof item === "number" ||
          typeof item === "boolean") {
        out[key] = item;
      }
    });
    return out;
  }

  /* ── 서버 스냅샷 → QuoteDraft 입력 ──
     역사적 sender 스냅샷이 authority 다. 현재 CompanyProfile 은 이 경로에
     없으므로 조용히 덮어쓸 수 없다(구조적 보장). */
  function historySnapshotToDraft(snapshot) {
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return null;

    var base = Core.createProductionDraft();
    var recipientRaw = snapshotObject(snapshot.recipient);
    var senderRaw = snapshotObject(snapshot.sender);
    var recipientString = boundedText(snapshot.recipient, 240);

    var meta = {
      quoteNo: boundedText(snapshot.quotationNo, 80) || base.meta.quoteNo,
      issueDate: boundedText(snapshot.issueDate, 40) || base.meta.issueDate,
      validDays: boundedNumber(snapshot.validityDays, base.meta.validDays),
      source: boundedText(snapshot.sourceKind, 40) || "manual"
    };
    var projectName = boundedText(snapshot.projectName, 240);
    if (projectName) meta.projectName = projectName;

    var itemsRaw = Array.isArray(snapshot.items) && snapshot.items.length
      ? snapshot.items
      : null;
    var items = (itemsRaw || base.items).map(function (item) {
      var raw = snapshotObject(item);
      var row = { name: boundedText(raw.name, 240), qty: boundedNumber(raw.qty, 1),
                  unitPrice: boundedNumber(raw.unitPrice, 0) };
      var spec = boundedText(raw.spec, 240);
      var unit = boundedText(raw.unit, 80);
      var note = boundedText(raw.note, 500);
      if (spec) row.spec = spec;
      if (unit) row.unit = unit;
      if (note) row.note = note;
      return row;
    });

    var taxMode = Core.TAX_MODES[snapshot.taxMode] ? snapshot.taxMode : base.tax.mode;

    return Core.normalizeDraft({
      schemaVersion: Core.SCHEMA_VERSION,
      meta: meta,
      sender: {
        company: boundedText(senderRaw.company, 240),
        rep: boundedText(senderRaw.rep, 80),
        contactPerson: boundedText(senderRaw.contactPerson, 80),
        bizNo: boundedText(senderRaw.bizNo, 80),
        address: boundedText(senderRaw.address, 240),
        phone: boundedText(senderRaw.phone, 80),
        email: boundedText(senderRaw.email, 240),
        presetId: boundedText(senderRaw.presetId, 40) || base.sender.presetId
      },
      recipient: {
        company: boundedText(recipientRaw.company, 240) || recipientString,
        person: boundedText(recipientRaw.person, 80),
        address: boundedText(recipientRaw.address, 240),
        email: boundedText(recipientRaw.email, 240)
      },
      items: items,
      tax: { mode: taxMode, rate: boundedNumber(snapshot.vatRate, base.tax.rate) },
      memo: typeof snapshot.memo === "string" ? snapshot.memo.slice(0, 2000) : ""
    });
  }

  /* ── 서버 projection 정규화 ──
     list projection 에는 snapshot 이 없고 detail projection 에는 있다.
     totals 관련 필드는 계약 표시일 뿐이며 어떤 값으로도 사용하지 않는다. */
  function normalizeProjection(row, options) {
    if (!row || typeof row !== "object" || Array.isArray(row)) return null;
    var id = boundedText(row.quote_history_id, 60);
    if (!ROW_ID_PATTERN.test(id)) return null;

    var includeSnapshot = !options || options.includeSnapshot !== false;
    var projection = {
      quoteHistoryId: id,
      quoteNo: boundedText(row.quote_no, 80),
      issueDate: boundedText(row.issue_date, 40),
      savedSkillId: boundedText(row.saved_skill_id, 64),
      skillFingerprint: boundedText(row.skill_fingerprint, 64),
      createdAt: boundedText(row.created_at, 80),
      updatedAt: boundedText(row.updated_at, 80),
      totalsAuthority: row.totals_authority === "quote-core" ? "quote-core" : null,
      quoteCoreRecalculationRequired: row.quote_core_recalculation_required === true
    };
    if (includeSnapshot) {
      if (!row.snapshot || typeof row.snapshot !== "object" || Array.isArray(row.snapshot)) {
        return null;
      }
      projection.snapshot = clone(row.snapshot);
      if (row.sender && typeof row.sender === "object" && !Array.isArray(row.sender)) {
        projection.sender = clone(row.sender);
      }
    }
    return projection;
  }

  /* ── API client ──
     응답 실패는 항상 bounded code 로 정규화된다. 네트워크 오류와 서버 오류는
     localStorage 로 대체되지 않고 그대로 호출자에게 돌아온다. */
  function resolveFetch(options) {
    if (options && typeof options.fetch === "function") return options.fetch;
    return typeof fetch === "function" ? fetch : null;
  }

  function errorCode(data, status) {
    if (data && data.error && typeof data.error.code === "string" && data.error.code) {
      return data.error.code;
    }
    return "http_" + String(status || 0);
  }

  function buildRequest(method, path, body) {
    var init = { method: method, credentials: "same-origin", cache: "no-store" };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    return init;
  }

  function parseEnvelope(data) {
    if (!data || typeof data !== "object" || data.ok !== true) return null;
    return data;
  }

  async function request(method, path, body, options) {
    var impl = resolveFetch(options);
    if (!impl) return { ok: false, code: "fetch_unavailable", status: 0 };
    var response;
    try {
      response = await impl(QUOTES_API_BASE + path, buildRequest(method, path, body));
    } catch (err) {
      return { ok: false, code: "network_error", status: 0 };
    }
    var status = typeof response.status === "number" ? response.status : 0;
    var data = null;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    if (!response.ok) return { ok: false, code: errorCode(data, status), status: status };
    var envelope = parseEnvelope(data);
    if (!envelope) return { ok: false, code: "invalid_response", status: status };
    return { ok: true, status: status, data: envelope };
  }

  function boundedLimit(raw) {
    var n = Number(raw);
    if (!Number.isFinite(n)) return MAX_LIST_LIMIT;
    return Math.max(1, Math.min(Math.floor(n), MAX_LIST_LIMIT));
  }

  function listQuotes(options) {
    var limit = boundedLimit(options && options.limit);
    return request("GET", "?limit=" + String(limit), undefined, options)
      .then(function (result) {
        if (!result.ok) return result;
        var quotes = Array.isArray(result.data.quotes) ? result.data.quotes : [];
        var normalized = [];
        quotes.forEach(function (row) {
          var projection = normalizeProjection(row, { includeSnapshot: false });
          if (projection) normalized.push(projection);
        });
        return { ok: true, quotes: normalized, limit: boundedLimit(result.data.limit) };
      });
  }

  function getQuote(quoteHistoryId, options) {
    var id = boundedText(quoteHistoryId, 60);
    if (!ROW_ID_PATTERN.test(id)) {
      return Promise.resolve({ ok: false, code: "invalid_quote_history_id", status: 0 });
    }
    return request("GET", "/" + id, undefined, options).then(function (result) {
      if (!result.ok) return result;
      var projection = normalizeProjection(result.data.quote);
      if (!projection) return { ok: false, code: "invalid_response", status: result.status };
      return { ok: true, quote: projection };
    });
  }

  function saveQuote(snapshot, options) {
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      return Promise.resolve({ ok: false, code: "invalid_snapshot", status: 0 });
    }
    return request("POST", "", snapshot, options).then(function (result) {
      if (!result.ok) return result;
      var projection = normalizeProjection(result.data.quote);
      if (!projection) return { ok: false, code: "invalid_response", status: result.status };
      return { ok: true, quote: projection };
    });
  }

  function deleteQuote(quoteHistoryId, options) {
    var id = boundedText(quoteHistoryId, 60);
    if (!ROW_ID_PATTERN.test(id)) {
      return Promise.resolve({ ok: false, code: "invalid_quote_history_id", status: 0 });
    }
    return request("DELETE", "/" + id, undefined, options).then(function (result) {
      if (!result.ok) return result;
      if (result.data.deleted !== id) {
        return { ok: false, code: "invalid_response", status: result.status };
      }
      return { ok: true, deleted: id };
    });
  }

  return {
    SNAPSHOT_SCHEMA: SNAPSHOT_SCHEMA,
    QUOTES_API_BASE: QUOTES_API_BASE,
    ROW_ID_PATTERN: ROW_ID_PATTERN,
    MAX_LIST_LIMIT: MAX_LIST_LIMIT,
    draftToHistorySnapshot: draftToHistorySnapshot,
    historySnapshotToDraft: historySnapshotToDraft,
    normalizeProjection: normalizeProjection,
    listQuotes: listQuotes,
    getQuote: getQuote,
    saveQuote: saveQuote,
    deleteQuote: deleteQuote
  };
});
