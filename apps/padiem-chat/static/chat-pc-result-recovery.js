(function (root) {
  "use strict";
  var RUN_ID = /^chat_pcq_[0-9a-f]{32}$/;
  var CONVERSATION_ID = /^chat_[0-9a-f]{32}$/;
  var PENDING = Object.freeze({pending: true, running: true});

  function create(options) {
    var opts = options || {};
    var fetchImpl = opts.fetchImpl || root.fetch.bind(root);
    var sleep = opts.sleep || function (ms, signal) {
      return new Promise(function (resolve, reject) {
        if (signal && signal.aborted) {
          var aborted = new Error("aborted");
          aborted.name = "AbortError";
          reject(aborted);
          return;
        }
        var timer = root.setTimeout(resolve, ms);
        if (signal && typeof signal.addEventListener === "function") {
          signal.addEventListener("abort", function () {
            root.clearTimeout(timer);
            var aborted = new Error("aborted");
            aborted.name = "AbortError";
            reject(aborted);
          }, {once: true});
        }
      });
    };
    var resolved = new Set();
    var attempted = new Set();
    // Runs the server answered 404 for. A 404 says the result does not exist,
    // not "not yet": every check that sees one stops for good, and a later
    // check for the same run answers from here without any new GET.
    var gone = new Set();

    function scopeNotice(result) {
      var notice = result && result.scope_notice;
      return typeof notice === "string" && notice ? notice : null;
    }

    async function read(runId, conversationId, signal) {
      if (!RUN_ID.test(runId)) return {kind: "rejected"};
      if (resolved.has(runId)) return {kind: "duplicate"};
      if (gone.has(runId)) return {kind: "rejected", status: 404, gone: true};
      var response;
      try {
        response = await fetchImpl(
          "/api/claw/runs/" + encodeURIComponent(runId) + "/pending-result",
          {
            method: "GET",
            headers: {Accept: "application/json"},
            cache: "no-store",
            credentials: "same-origin",
            signal: signal
          }
        );
      } catch (error) {
        if (error && error.name === "AbortError") throw error;
        return {kind: "unavailable"};
      }
      if (!response || !response.ok) {
        var status = response && response.status;
        if (status === 404) gone.add(runId);
        return {
          kind: (status === 401 || status === 403 || status === 404) ? "rejected" : "unavailable",
          status: status,
          gone: status === 404
        };
      }
      var data;
      try {
        data = await response.json();
      } catch (_) {
        return {kind: "unavailable"};
      }
      var result = data && data.result;
      if (!result || result.run_id !== runId) return {kind: "rejected"};
      var cid = result.conversation_id;
      if (typeof cid !== "string" || !CONVERSATION_ID.test(cid)) return {kind: "rejected"};
      if (conversationId && cid !== conversationId) return {kind: "rejected"};
      if (PENDING[result.status] === true) {
        return {
          kind: "pending", conversationId: cid, status: result.status,
          scopeNotice: scopeNotice(result)
        };
      }
      if (result.status !== "completed"
          || typeof result.answer !== "string" || !result.answer
          || (result.answer_source !== "pc_command_result"
              && result.answer_source !== "model_reply")) {
        return {kind: "failed", conversationId: cid, status: result.status};
      }
      resolved.add(runId);
      return {
        kind: "completed",
        answer: result.answer,
        answerSource: result.answer_source,
        conversationId: cid,
        scopeNotice: scopeNotice(result)
      };
    }

    async function recoverOnce(handle) {
      var details = handle || {};
      var runId = details.runId;
      if (typeof runId !== "string" || !RUN_ID.test(runId)) return {kind: "rejected"};
      if (attempted.has(runId)) return {kind: "duplicate"};
      attempted.add(runId);
      return read(runId, details.conversationId, details.signal);
    }

    async function waitForResult(handle) {
      var details = handle || {};
      var runId = details.runId;
      var conversationId = details.conversationId;
      var signal = details.signal;
      // #5895: no default give-up. A PC turn that takes minutes is the same
      // turn, and the server keeps its answer; stopping the read-back after a
      // fixed number of attempts only turned a running task into a dead screen.
      // An explicit caller-supplied bound is still honoured.
      var maxAttempts = Number.isInteger(details.maxAttempts) && details.maxAttempts > 0
        ? details.maxAttempts : null;
      var intervalMs = Number.isInteger(details.intervalMs) && details.intervalMs >= 0
        ? details.intervalMs : 2000;
      var onPending = typeof details.onPending === "function" ? details.onPending : null;
      var last = {kind: "pending"};
      for (var attempt = 0; maxAttempts === null || attempt < maxAttempts; attempt += 1) {
        if (signal && signal.aborted) {
          var aborted = new Error("aborted");
          aborted.name = "AbortError";
          throw aborted;
        }
        last = await read(runId, conversationId, signal);
        if (last.kind !== "pending") return last;
        // The caller keeps its own wording truthful between reads; this cannot
        // end the turn and cannot start another one.
        if (onPending) onPending(last);
        if (maxAttempts === null || attempt + 1 < maxAttempts) await sleep(intervalMs, signal);
      }
      return {kind: "pending", conversationId: last.conversationId || conversationId || null};
    }

    return Object.freeze({recoverOnce: recoverOnce, waitForResult: waitForResult});
  }

  root.PadiemChatPcRecovery = Object.freeze({
    create: create,
    validRunId: function (value) { return typeof value === "string" && RUN_ID.test(value); }
  });
})(typeof window !== "undefined" ? window : globalThis);
