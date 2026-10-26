(() => {
  "use strict";

  let orchestrationPauseHandler = null;
  const orchestrationRequests = new WeakMap();
  const calendarTurnIdsByRequest = new WeakMap();

  function errorFor(data, fallback) {
    const message = data && data.error && typeof data.error.message === "string" && data.error.message.trim() ? data.error.message : fallback;
    const error = new Error(message);
    if (data && data.error && typeof data.error.code === "string") error.code = data.error.code;
    if (data && data.ok === false && data.error) error.terminalRecord = true;
    return error;
  }

  function streamErrorMessage(data) {
    const code = data?.error?.code;
    if (code === "upstream_timeout") return "응답 시간이 초과되었습니다. 다시 시도해 주세요.";
    return typeof code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(code)
      ? `요청을 처리하지 못했습니다 (${code}). 다시 시도해 주세요.`
      : "요청을 처리하지 못했습니다. 다시 시도해 주세요.";
  }

  function normalizeStreamFrame(frame) {
    if (!frame) return frame;
    try {
      const data = JSON.parse(frame.data);
      if (data?.ok === false && data.error) return { ...frame, event: "error" };
    } catch (_) { /* The consumer owns malformed record reporting. */ }
    return frame;
  }

  function isStreamResponse(response) {
    const type = (response?.headers?.get("content-type") || "").toLowerCase();
    return type.startsWith("text/event-stream") || type.startsWith("application/x-ndjson")
      || type.startsWith("application/ndjson");
  }

  function parseSseFrame(frame) {
    const lines = frame.replace(/\r\n/g, "\n").split("\n");
    let event = "message";
    const dataLines = [];
    lines.forEach((line) => {
      if (!line || line.startsWith(":")) return;
      const separator = line.indexOf(":");
      const field = separator >= 0 ? line.slice(0, separator) : line;
      let value = separator >= 0 ? line.slice(separator + 1) : "";
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      if (field === "data") dataLines.push(value);
    });
    if (!dataLines.length) return null;
    return normalizeStreamFrame({ event, data: dataLines.join("\n") });
  }

  async function readSseEvents(response, onEvent) {
    if (!response.body || typeof response.body.getReader !== "function") throw new Error("스트리밍 응답을 읽을 수 없습니다.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    const ndjson = /application\/(?:x-)?ndjson/i.test(response.headers?.get("content-type") || "");
    let buffer = "";
    let reachedEof = false;
    let stoppedEarly = false;
    try {
      async function consume(frame) {
        if (frame && frame.event === "orchestration_pause" && orchestrationRequests.has(response)) {
          const data = JSON.parse(frame.data);
          notifyOrchestrationPause(data.orchestration, orchestrationRequests.get(response));
          const paused = new Error("approval paused");
          paused.name = "AbortError";
          throw paused;
        }
        return frame && await onEvent(frame);
      }
      function parseRecord(text) {
        if (!ndjson) return parseSseFrame(text);
        if (!text.trim()) return null;
        const data = JSON.parse(text);
        const event = data.event || (data.done === true ? "done" : typeof data.delta === "string" ? "delta" : "message");
        return normalizeStreamFrame({ event, data: text });
      }
      while (true) {
        const item = await reader.read();
        if (item.done) {
          reachedEof = true;
          break;
        }
        buffer += decoder.decode(item.value, { stream: true });
        while (true) {
          const boundary = buffer.match(ndjson ? /\r?\n/ : /\r?\n\r?\n/);
          if (!boundary || boundary.index === undefined) break;
          const frameText = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          const frame = parseRecord(frameText);
          if (await consume(frame)) {
            stoppedEarly = true;
            return;
          }
        }
      }
      buffer += decoder.decode();
      if (ndjson && buffer.trim()) {
        await consume(parseRecord(buffer));
        buffer = "";
      }
      if (buffer.trim()) throw new Error("AI 스트리밍 응답이 완전히 끝나지 않았습니다.");
    } finally {
      if (!reachedEof || stoppedEarly) {
        try { await reader.cancel(); } catch (_) { /* no-op */ }
      }
      reader.releaseLock();
    }
  }

  function createCalendarTurnId() {
    return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID() : null;
  }

  function createChatPcRunId() {
    if (typeof crypto === "undefined") return null;
    if (typeof crypto.randomUUID === "function") {
      return "chat_pcq_" + crypto.randomUUID().replace(/-/g, "");
    }
    if (typeof crypto.getRandomValues === "function") {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      return "chat_pcq_" + Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    }
    return null;
  }

  function calendarRequestFields(payload) {
    const result = { ...payload };
    if (typeof result.timezone !== "string" || !result.timezone) {
      try { result.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (_) { result.timezone = ""; }
    }
    if (typeof result.calendar_turn_id !== "string" || !result.calendar_turn_id) {
      let stableId = calendarTurnIdsByRequest.get(payload);
      if (!stableId) {
        stableId = createCalendarTurnId();
        if (stableId) calendarTurnIdsByRequest.set(payload, stableId);
      }
      if (stableId) result.calendar_turn_id = stableId;
    }
    if (!result.calendar_turn_id) delete result.calendar_turn_id;
    if (!result.timezone) delete result.timezone;
    return result;
  }

  function withDeviceSelection(payload) {
    // One shared preference for Chat and Claw. A hint only: the server
    // re-verifies the saved target against current authority and connection.
    const chosen = typeof window.padiemSelectedDeviceId === "function"
      ? window.padiemSelectedDeviceId()
      : (typeof window.padiemClawSelectedDeviceId === "function"
        ? window.padiemClawSelectedDeviceId() : null);
    const wire = calendarRequestFields(payload);
    return typeof chosen === "string" && chosen
      ? { ...wire, device_id: chosen }
      : wire;
  }

  // #2505: one attachment wire for both product lanes. A text document stays in
  // the JSON body; a binary original (PDF/DOCX/PPTX/XLSX) or an image travels as
  // the header+bytes frame the server decodes. Chat and Claw send the same
  // bytes, so neither lane grows its own attachment encoding.
  function attachmentRequestBody(wire) {
    const attachment = Array.isArray(wire.attachments) && wire.attachments.length === 1 ? wire.attachments[0] : null;
    const binary = attachment && attachment.file;
    if (!binary) return { body: JSON.stringify(wire), contentType: "application/json" };
    const metadata = { ...wire, attachments: [{ type: attachment.type, name: attachment.name, media_type: attachment.media_type }] };
    const header = new TextEncoder().encode(JSON.stringify(metadata));
    if (header.byteLength > 65536) throw new Error("첨부 메타데이터가 너무 큽니다.");
    const prefix = new Uint8Array(4);
    new DataView(prefix.buffer).setUint32(0, header.byteLength, false);
    return {
      body: new Blob([prefix, header, binary], { type: "application/octet-stream" }),
      contentType: "application/octet-stream",
    };
  }

  async function requestCompleted(payload, signal) {
    const wire = withDeviceSelection(payload);
    const { body, contentType } = attachmentRequestBody(wire);
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": contentType, "Accept": "application/json" },
      body,
      signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || typeof data.answer !== "string") {
      throw errorFor(data, "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.");
    }
    return data;
  }

  async function orchestrationReady(signal) {
    try {
      const response = await fetch("/api/orchestration/status", {
        method: "GET",
        headers: { "Accept": "application/json" },
        cache: "no-store",
        signal,
      });
      if (!response.ok) return false;
      const data = await response.json().catch(() => null);
      return Boolean(data && data.orchestration_ready === true && data.authenticated === true);
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      return false;
    }
  }

  async function postOrchestration(path, payload, signal) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
    if (response.ok && isStreamResponse(response)) {
      orchestrationRequests.set(response, payload);
      return response;
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || data.ok === false) {
      throw errorFor(data, streamErrorMessage(data));
    }
    return data;
  }

  function setOrchestrationPauseHandler(handler) {
    if (handler !== null && typeof handler !== "function") throw new TypeError("orchestration pause handler must be a function or null");
    orchestrationPauseHandler = handler;
  }

  function notifyOrchestrationPause(orchestration, requestPayload) {
    if (typeof orchestrationPauseHandler !== "function") {
      throw new Error("확인 화면을 표시할 수 없습니다.");
    }
    orchestrationPauseHandler(Object.freeze({ orchestration, requestPayload }));
  }

  async function resumeOrchestration(intent, signal) {
    return postOrchestration("/api/orchestration/resume", intent, signal);
  }

  async function cancelOrchestration(intent, signal) {
    return postOrchestration("/api/orchestration/cancel", intent, signal);
  }

  function syntheticSseResponse(data) {
    const delta = `event: delta\ndata: ${JSON.stringify({ delta: data.answer })}\n\n`;
    const donePayload = { done: true };
    if (typeof data.conversation_id === "string") donePayload.conversation_id = data.conversation_id;
    // #4469: a grounded answer carries its tool marker and its public
    // evidence. They reach the browser here so the answer can show the
    // sources it was actually grounded with, exactly like the Chat stream
    // route already does.
    if (typeof data.answer_status === "string") donePayload.answer_status = data.answer_status;
    if (typeof data.notice === "string") donePayload.notice = data.notice;
    if (data.metadata && typeof data.metadata === "object") donePayload.metadata = data.metadata;
    // #5573: the completed PC lane response carries the pinned scope notice as
    // its own field. It rides the completion frame so the live answer shows
    // the same notice a reload would show; the answer text is untouched.
    if (typeof data.scope_notice === "string" && data.scope_notice) donePayload.scope_notice = data.scope_notice;
    if (Array.isArray(data.evidence) && data.evidence.length) donePayload.evidence = data.evidence;
    if (data.tool && typeof data.tool === "object") donePayload.tool = data.tool;
    const done = `event: done\ndata: ${JSON.stringify(donePayload)}\n\n`;
    return new Response(delta + done, {
      status: 200,
      headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  async function tryOrchestration(payload, signal, required = false) {
    if (!await orchestrationReady(signal)) {
      if (required) throw errorFor({error: {code: "orchestration_unavailable", message: "AI 작업 연결을 현재 사용할 수 없습니다."}});
      return null;
    }
    let data;
    try {
      data = await postOrchestration("/api/orchestration", payload, signal);
    } catch (error) {
      if (error && error.code === "orchestration_not_applicable") return null;
      throw error;
    }
    if (isStreamResponse(data)) {
      return data;
    }
    if (data.orchestration && data.orchestration.approval_pause) {
      notifyOrchestrationPause(data.orchestration, payload);
      const paused = new Error("approval paused");
      paused.name = "AbortError";
      throw paused;
    }
    if (typeof data.answer !== "string" || !data.answer) {
      throw new Error("AI 작업 응답을 확인할 수 없습니다.");
    }
    return syntheticSseResponse(data);
  }

  async function clawLiveEventsAvailable(signal) {
    // Readiness only. No execution, quota consumption, read ACK, or retry.
    try {
      const response = await fetch("/api/claw/general/capabilities", {
        method: "GET",
        headers: { "Accept": "application/json" },
        cache: "no-store",
        signal,
      });
      if (!response.ok) return false;
      const data = await response.json().catch(() => null);
      return !!(data && data.live_events_available === true);
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      return false; // Conservative completed-path behavior, before dispatch.
    }
  }

  async function requestClawGeneral(payload, signal) {
    // #3539: the B54 Claw general composer runs on the canonical P01 Engine
    // lane. There is deliberately NO fallback to the standalone B62
    // /api/chat/stream direct-B14 route: an unavailable P01 lane surfaces as a
    // bounded error instead of silently changing products.
    const liveReady = await clawLiveEventsAvailable(signal);
    // Reuse the existing owner-scoped PC chooser; no manual device ID input.
    // The selected id is only a hint: canonical Identity/Broker decide authority.
    const wired = withDeviceSelection(payload);
    // #2505: an attached document uses the same wire as Chat, including the
    // binary frame for a PDF/DOCX/PPTX/XLSX original.
    const { body, contentType: requestContentType } = attachmentRequestBody(wired);
    const headers = { "Content-Type": requestContentType, "Accept": "text/event-stream" };
    if (liveReady) headers["X-Padiem-Claw-Live"] = "p01-events-v1";
    const response = await fetch("/api/claw/general", {
      method: "POST",
      headers,
      body,
      signal,
    });
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    if (!response.ok || !contentType.startsWith("text/event-stream")) {
      const data = await response.json().catch(() => null);
      const error = errorFor(data, "AI 작업을 처리하지 못했습니다. 다시 시도해 주세요.");
      // #3566: preserve ONLY the closed, source-owned rate-limit classification
      // for Claw presentation. Never trust a provider message as the category.
      if (response.status === 502 && data?.error?.code === "engine_execution_failed" &&
          data?.error?.detail === "engine_provider_rate_limited") {
        error.clawFailureDetail = "engine_provider_rate_limited";
      }
      throw error;
    }
    return response;
  }

  async function requestStreaming(payload, signal) {
    const wire = withDeviceSelection(payload);
    // The server-owned opt-in defaults off; the legacy custom path stays exact.
    const byokViaB14 = payload && payload.custom && window.PadiemCustomSelection?.viaB14?.() === true;
    const orchestrated = payload && payload.custom && !byokViaB14
      ? null : await tryOrchestration(byokViaB14 ? wire : payload, signal, byokViaB14);
    if (orchestrated) return orchestrated;

    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(wire),
      signal,
    });
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    if (!response.ok || !contentType.startsWith("text/event-stream")) {
      const data = await response.json().catch(() => null);
      throw errorFor(data, "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.");
    }
    return response;
  }

  window.PadiemChatTransport = Object.freeze({
    createCalendarTurnId,
    createChatPcRunId,
    errorFor,
    streamErrorMessage,
    parseSseFrame,
    readSseEvents,
    requestCompleted,
    requestClawGeneral,
    requestStreaming,
    orchestrationReady,
    resumeOrchestration,
    cancelOrchestration,
    setOrchestrationPauseHandler,
  });
})();
