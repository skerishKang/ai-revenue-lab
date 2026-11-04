(() => {
  "use strict";

  let orchestrationPauseHandler = null;
  const orchestrationRequests = new WeakMap();
  const calendarTurnIdsByRequest = new WeakMap();

  // #6732: 탭(세션) 안에서 상태 확인 결과를 재사용한다. 성공만 캐시하고,
  // 실패·401·가용성 신호를 받으면 즉시 버려 다음 턴에 다시 묻는다.
  const ORCHESTRATION_STATUS_TTL_MS = 5 * 60 * 1000;
  let orchestrationReadyAt = 0;
  // Console/debug override. Streaming is on by default; setting this global to
  // false restores the pre-NDJSON orchestration request path for this tab.
  function orchestrationStreamingEnabled() {
    return window.PADIEM_CHAT_ORCHESTRATION_STREAM !== false;
  }
  function invalidateOrchestrationReady() { orchestrationReadyAt = 0; }
  function orchestrationReadyCached() {
    return orchestrationReadyAt > 0 && Date.now() - orchestrationReadyAt < ORCHESTRATION_STATUS_TTL_MS;
  }

  function errorFor(data, fallback, status) {
    // Keep server text out of the screen; retain the code for recovery and the reference note.
    const message = streamErrorMessage(data, status);
    const error = new Error(message);
    if (data && data.error && typeof data.error.code === "string") error.code = data.error.code;
    if (status === 422 || (data && data.ok === false && data.error)) error.terminalRecord = true;
    // A refused submit POST is not a cut stream: the PC run handle is minted
    // before the request goes out, so when the HTTP response itself says no
    // (status >= 400 is passed only by the submit call sites), that run was
    // never created and reading its pending-result can only return 404. The
    // recovery guard in app.js uses this to skip the check entirely; a stream
    // that stopped after acceptance throws without a status and still recovers.
    if (Number.isInteger(status) && status >= 400) error.submissionRejected = true;
    return error;
  }

  // #5895: these two codes are produced when an Engine stream stops without a
  // verified result — the run itself keeps going and its answer is stored. A
  // refusal (authorization, tier, cancellation, execution failure) never uses
  // them, so only these may hand the turn to the pending-result recovery.
  const STREAM_LOSS_CODES = new Set(["invalid_engine_stream", "invalid_engine_stream_event"]);

  function isStreamLoss(data) {
    return STREAM_LOSS_CODES.has(data?.error?.code);
  }

  function streamErrorMessage(data, status) {
    const code = data?.error?.code;
    switch (code) {
      case "stale_chat_client":
        return "화면이 오래되었습니다. 새로고침한 뒤 다시 시도해 주세요.";
      case "upstream_timeout":
        return "응답 시간이 초과되었습니다. 다시 시도해 주세요.";
      case "custom_credential_required":
        return "먼저 API 키를 등록해 주세요.";
      case "custom_key_invalid":
      case "custom_provider_auth_failed":
      case "byok_auth_failed":
        return "API 키를 확인해 주세요.";
      case "invalid_request":
        // Attachment validation currently shares invalid_request. Match only
        // known fixed messages and return local text, never arbitrary server text.
        switch (data?.error?.message) {
          case "HWPX 파일에서 읽을 내용을 찾지 못했습니다.":
            return "HWPX 파일에서 읽을 내용을 찾지 못했습니다.";
          case "HWPX 파일에서 읽을 글자를 찾지 못했습니다. 이미지나 표는 일부 읽지 못할 수 있습니다.":
            return "HWPX 파일에서 읽을 글자를 찾지 못했습니다. 이미지나 표는 일부 읽지 못할 수 있습니다.";
          case "HWPX 파일 형식을 확인해 주세요.":
            return "HWPX 파일 형식을 확인해 주세요.";
          case "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요.":
            return "암호화된 문서라 열 수 없습니다. 암호를 풀고 다시 올려 주세요.";
          case "암호화된 DOCX는 현재 첨부할 수 없습니다.":
            return "암호화된 DOCX는 현재 첨부할 수 없습니다.";
          case "암호화된 PDF는 현재 첨부할 수 없습니다.":
            return "암호화된 PDF는 현재 첨부할 수 없습니다.";
          case "암호화된 PPTX는 현재 첨부할 수 없습니다.":
            return "암호화된 PPTX는 현재 첨부할 수 없습니다.";
          case "암호화된 XLSX는 현재 첨부할 수 없습니다.":
            return "암호화된 XLSX는 현재 첨부할 수 없습니다.";
          case "암호화된 문서는 현재 첨부할 수 없습니다.":
            return "암호화된 문서는 현재 첨부할 수 없습니다.";
        }
      case "input_schema_rejected":
        return "요청 내용을 확인할 수 없습니다. 내용을 확인한 뒤 다시 시도해 주세요.";
      case "entitlement_unavailable":
      case "live_abuse_gate_unavailable":
      case "orchestration_unavailable":
      case "ai_chat_unavailable":
      case "engine_not_configured":
      case "provider_server_error":
        return "지금은 서비스를 이용할 수 없습니다. 잠시 후 다시 시도해 주세요.";
      default:
        if (!code && status === 503) return "지금은 서비스를 이용할 수 없습니다. 잠시 후 다시 시도해 주세요.";
        return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
    }
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
        // Public Chat frames use type/text records; selected Engine progress
        // records use ok + event/text_delta/pc_progress/heartbeat/error.
        // Normalize them without forwarding private messages or IDs.
        if (typeof data.type === "string") {
          if (data.type === "delta" && typeof data.text === "string") {
            return { event: "delta", data: JSON.stringify({ delta: data.text }) };
          }
          if (data.type === "error") {
            return { event: "error", data: JSON.stringify({ error: { code: data.code } }) };
          }
          if (data.type === "event") {
            return { event: "orchestration_event", data: JSON.stringify(data.event || {}) };
          }
          if (data.type === "tool") {
            return { event: "tool", data: JSON.stringify(data.tool || {}) };
          }
          if (data.type === "thought_summary") {
            return { event: "thought_summary", data: JSON.stringify({ summary: data.summary }) };
          }
          if (data.type === "pc_progress") {
            return { event: "pc_progress", data: JSON.stringify(data.pc_progress || data.progress || {}) };
          }
          if (data.type === "heartbeat") {
            return { event: "heartbeat", data: JSON.stringify(data.heartbeat || data) };
          }
          return normalizeStreamFrame({ event: data.type, data: text });
        }
        if (data.text_delta && typeof data.text_delta.delta === "string") {
          return { event: "delta", data: JSON.stringify({ delta: data.text_delta.delta }) };
        }
        if (data.event && typeof data.event === "object") {
          return { event: "orchestration_event", data: JSON.stringify(data.event) };
        }
        if (data.pc_progress && typeof data.pc_progress === "object") {
          return { event: "pc_progress", data: JSON.stringify(data.pc_progress) };
        }
        if (data.heartbeat && typeof data.heartbeat === "object") {
          return { event: "heartbeat", data: JSON.stringify(data.heartbeat) };
        }
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
    // An empty answer is not an answer. The streaming path already refuses a
    // blank completion; without this the completed path committed an empty turn
    // and left the user staring at a bubble with nothing in it.
    if (!response.ok || !data || typeof data.answer !== "string") {
      throw errorFor(data, "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.", response.status);
    }
    if (!data.answer.trim()) {
      throw errorFor(data, "답변이 비어 왔습니다. 다시 시도해 주세요.", response.status);
    }
    return data;
  }

  async function orchestrationReady(signal) {
    if (orchestrationReadyCached()) return true;
    try {
      const response = await fetch("/api/orchestration/status", {
        method: "GET",
        headers: { "Accept": "application/json" },
        cache: "no-store",
        signal,
      });
      if (!response.ok) { invalidateOrchestrationReady(); return false; }
      const data = await response.json().catch(() => null);
      const ready = Boolean(data && data.orchestration_ready === true && data.authenticated === true);
      // 준비되지 않았거나 로그인이 아니면 캐시하지 않는다: 레인이 바뀌면 바로 따라간다.
      if (ready) orchestrationReadyAt = Date.now(); else invalidateOrchestrationReady();
      return ready;
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      invalidateOrchestrationReady();
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
    // 401·503은 로그인이나 가용성이 바뀌었다는 신호다. 캐시를 버리고 다음 턴에 다시 묻는다.
    if (response.status === 401 || response.status === 503) invalidateOrchestrationReady();
    if (response.ok && isStreamResponse(response)) {
      orchestrationRequests.set(response, payload);
      return response;
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || data.ok === false) {
      throw errorFor(data, streamErrorMessage(data), response.status);
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

  // A signed-out session can never be ready for orchestration (the status
  // answer requires authenticated === true). When the page has already read
  // the session as a guest, asking the endpoint again would serialize one
  // extra round trip before every answer request of a guest, including the
  // request that ends in an immediate refusal. Skip the probe then.
  function sessionDefinitelyNotOrchestratable() {
    try {
      const state = window.PadiemProductCapabilities?.get?.();
      const auth = state && state.auth;
      return Boolean(auth && auth.loaded === true && auth.ready === true
        && auth.authenticated !== true);
    } catch (_) {
      return false;
    }
  }

  async function tryOrchestration(payload, signal, required = false) {
    if (!required && sessionDefinitelyNotOrchestratable()) return null;
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
    const byokViaB14 = payload && payload.custom && window.PadiemCustomSelection?.viaEngine?.() === true;
    const orchestrationPayload = byokViaB14 ? wire : payload;
    const orchestrated = payload && payload.custom && !byokViaB14
      ? null
      : orchestrationStreamingEnabled()
        ? await requestOrchestrationStream(orchestrationPayload, signal, byokViaB14)
        : await tryOrchestration(orchestrationPayload, signal, byokViaB14);
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
      throw errorFor(data, "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.", response.status);
    }
    return response;
  }

  // #6742: server NDJSON line reader kept as a small testable transport helper.
  async function readOrchestrationNdjson(response, onFrame) {
    if (!response || !response.body || typeof response.body.getReader !== "function") {
      throw new Error("스트림 응답을 읽을 수 없습니다.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let stopped = false;
    let completed = false;
    try {
      while (!stopped) {
        const { done, value } = await reader.read();
        if (done) { completed = true; break; }
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n")) >= 0) {
          const raw = buffer.slice(0, index).trim();
          buffer = buffer.slice(index + 1);
          if (!raw) continue;
          let frame;
          try { frame = JSON.parse(raw); } catch { throw new Error("스트림 형식을 확인할 수 없습니다."); }
          if (await onFrame(frame) === true) { stopped = true; break; }
        }
      }
      const tail = buffer.trim();
      if (!stopped && tail) {
        let frame;
        try { frame = JSON.parse(tail); } catch { throw new Error("스트림 형식을 확인할 수 없습니다."); }
        await onFrame(frame);
      }
    } finally {
      if (!completed) {
        try { await reader.cancel?.(); } catch { /* reader is already closed */ }
      }
      try { reader.releaseLock(); } catch { /* 이미 닫힌 리더 */ }
    }
  }

  async function requestOrchestrationStream(payload, signal, required = false) {
    // #6799: the streaming lane owes the guest the same skip tryOrchestration
    // already has - a signed-out session can never be orchestration-ready, so
    // the probe would be one paid round trip before the refusal.
    if (!required && sessionDefinitelyNotOrchestratable()) return null;
    if (!orchestrationStreamingEnabled()) return tryOrchestration(payload, signal, required);
    if (!await orchestrationReady(signal)) {
      if (required) throw errorFor({ error: { code: "orchestration_unavailable" } });
      return null;
    }
    const response = await fetch("/api/orchestration", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/x-ndjson" },
      body: JSON.stringify(payload || {}),
      signal,
    });
    if (!response.ok) {
      if (response.status === 401 || response.status === 503) invalidateOrchestrationReady();
      const data = await response.json().catch(() => null);
      throw errorFor(data, streamErrorMessage(data), response.status);
    }
    // 플래그가 꺼져 있으면 서버는 지금과 같은 JSON을 준다: 호출자는 기존 경로를 쓴다.
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    if (response.ok && (contentType.includes("application/x-ndjson") || contentType.includes("application/ndjson"))) {
      return response;
    }
    if (response.ok && contentType.startsWith("text/event-stream")) {
      orchestrationRequests.set(response, payload);
      return response;
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || data.ok === false || data.error) {
      if (data?.error?.code === "orchestration_not_applicable") return null;
      throw errorFor(data, streamErrorMessage(data), response.status);
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

  window.PadiemChatTransport = Object.freeze({
    createCalendarTurnId,
    createChatPcRunId,
    errorFor,
    streamErrorMessage,
    isStreamLoss,
    parseSseFrame,
    readSseEvents,
    requestCompleted,
    requestClawGeneral,
    requestStreaming,
    orchestrationReady,
    orchestrationStreamingEnabled,
    invalidateOrchestrationReady,
    requestOrchestrationStream,
    readOrchestrationNdjson,
    resumeOrchestration,
    cancelOrchestration,
    setOrchestrationPauseHandler,
  });
})();
