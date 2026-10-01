/* B66 canonical browser render bridge (#3310).
   No storage, file intake, network access, model calls, or duplicate math.
   The bridge delegates all quote semantics to canonical SavedQuoteSkill,
   QuoteCore and QuoteTemplateRenderer modules already loaded by embed.html. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66QuoteEmbedBridge = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var REQUEST_TYPE = "b66.embed.render.v1";
  var RESPONSE_TYPE = "b66.embed.rendered.v1";
  var ERROR_TYPE = "b66.embed.error.v1";
  var PRINT_TYPE = "b66.embed.print.v1";
  var MAX_MESSAGE_JSON_CHARS = 128 * 1024;
  var REQUEST_REF_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function requestRef(value) {
    return typeof value === "string" && REQUEST_REF_RE.test(value) ? value : null;
  }

  function jsonSizeOkay(value) {
    try {
      return JSON.stringify(value).length <= MAX_MESSAGE_JSON_CHARS;
    } catch (_) {
      return false;
    }
  }

  function normalizeRenderMessage(value) {
    if (!isPlainObject(value) || value.type !== REQUEST_TYPE) return null;
    if (Object.keys(value).some(function (key) {
      return ["type", "requestId", "skill", "candidate"].indexOf(key) === -1;
    })) return null;
    var id = requestRef(value.requestId);
    if (!id || !isPlainObject(value.skill) || !isPlainObject(value.candidate)) return null;
    if (!jsonSizeOkay(value.skill) || !jsonSizeOkay(value.candidate)) return null;
    return {
      type: REQUEST_TYPE,
      requestId: id,
      skill: value.skill,
      candidate: value.candidate
    };
  }

  function buildStructuredInput(candidate, core) {
    if (!isPlainObject(candidate) || !core || typeof core.createDefaultDraft !== "function") {
      return null;
    }
    var defaults = core.createDefaultDraft();
    if (!defaults || !defaults.meta) return null;

    var input = {
      recipient: candidate.recipient,
      quoteNo: typeof candidate.quoteNo === "string" && candidate.quoteNo.trim()
        ? candidate.quoteNo.trim()
        : defaults.meta.quoteNo,
      issueDate: typeof candidate.issueDate === "string" && candidate.issueDate.trim()
        ? candidate.issueDate.trim()
        : defaults.meta.issueDate,
      items: candidate.items
    };
    if (typeof candidate.memo === "string") input.memo = candidate.memo;
    if (typeof candidate.taxMode === "string" && candidate.taxMode) input.taxMode = candidate.taxMode;
    return input;
  }

  function renderRequest(message, runtime, doc) {
    var normalized = normalizeRenderMessage(message);
    if (!normalized) return { ok: false, code: "invalid_embed_request" };
    if (
      !runtime ||
      !runtime.Core ||
      !runtime.SavedSkill ||
      !runtime.Renderer ||
      typeof runtime.SavedSkill.buildRenderModel !== "function" ||
      typeof runtime.Renderer.applyRenderModel !== "function"
    ) {
      return { ok: false, code: "embed_runtime_unavailable" };
    }

    var input = buildStructuredInput(normalized.candidate, runtime.Core);
    if (!input) return { ok: false, code: "invalid_embed_candidate" };

    var result = runtime.SavedSkill.buildRenderModel(normalized.skill, input);
    if (!result || result.ok !== true || !result.renderModel || !result.draft) {
      return {
        ok: false,
        code: result && typeof result.code === "string" ? result.code : "render_model_failed"
      };
    }
    var applied = runtime.Renderer.applyRenderModel(doc, result.renderModel);
    if (applied !== true) return { ok: false, code: "render_apply_failed" };

    var readiness = typeof runtime.Core.printReadiness === "function"
      ? runtime.Core.printReadiness(result.draft)
      : { ready: false, missing: ["runtime"] };
    return {
      ok: true,
      code: "rendered",
      requestId: normalized.requestId,
      quoteNo: result.draft.meta.quoteNo,
      issueDate: result.draft.meta.issueDate,
      printReady: Boolean(readiness && readiness.ready === true),
      missing: readiness && Array.isArray(readiness.missing) ? readiness.missing.slice(0, 8) : []
    };
  }

  function publicResponse(result, requestId) {
    if (!result || result.ok !== true) {
      return {
        type: ERROR_TYPE,
        requestId: requestId || null,
        ok: false,
        code: result && typeof result.code === "string" ? result.code : "render_failed"
      };
    }
    return {
      type: RESPONSE_TYPE,
      requestId: result.requestId,
      ok: true,
      code: result.code,
      quoteNo: result.quoteNo,
      issueDate: result.issueDate,
      printReady: result.printReady,
      missing: result.missing
    };
  }

  function installBrowserBridge(win, doc, runtime) {
    if (!win || !doc || typeof win.addEventListener !== "function") return false;
    win.addEventListener("message", function (event) {
      if (!event || event.source !== win.parent) return;
      if (event.data && event.data.type === PRINT_TYPE) {
        if (typeof win.print === "function") win.print();
        return;
      }
      var normalized = normalizeRenderMessage(event.data);
      if (!normalized) return;
      var result = renderRequest(normalized, runtime, doc);
      if (event.source && typeof event.source.postMessage === "function") {
        event.source.postMessage(publicResponse(result, normalized.requestId), event.origin);
      }
      var status = typeof doc.getElementById === "function" ? doc.getElementById("embedStatus") : null;
      if (status) {
        status.textContent = result.ok
          ? (result.printReady ? "견적서가 준비되었습니다." : "필수 내용을 확인해 주세요.")
          : "견적서를 만들지 못했습니다.";
        status.dataset.state = result.ok ? "ready" : "error";
      }
    });
    return true;
  }

  return {
    REQUEST_TYPE: REQUEST_TYPE,
    RESPONSE_TYPE: RESPONSE_TYPE,
    ERROR_TYPE: ERROR_TYPE,
    PRINT_TYPE: PRINT_TYPE,
    MAX_MESSAGE_JSON_CHARS: MAX_MESSAGE_JSON_CHARS,
    normalizeRenderMessage: normalizeRenderMessage,
    buildStructuredInput: buildStructuredInput,
    renderRequest: renderRequest,
    publicResponse: publicResponse,
    installBrowserBridge: installBrowserBridge
  };
});
