(() => {
  "use strict";

  let orchestrationPauseHandler = null;

  function errorFor(data, fallback) {
    const message = data && data.error && typeof data.error.message === "string" ? data.error.message : fallback;
    const error = new Error(message);
    if (data && data.error && typeof data.error.code === "string") error.code = data.error.code;
    return error;
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
    return { event, data: dataLines.join("\n") };
  }

  async function readSseEvents(response, onEvent) {
    if (!response.body || typeof response.body.getReader !== "function") throw new Error("스트리밍 응답을 읽을 수 없습니다.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let reachedEof = false;
    let stoppedEarly = false;
    try {
      while (true) {
        const item = await reader.read();
        if (item.done) {
          reachedEof = true;
          break;
        }
        buffer += decoder.decode(item.value, { stream: true });
        while (true) {
          const boundary = buffer.match(/\r?\n\r?\n/);
          if (!boundary || boundary.index === undefined) break;
          const frameText = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          const frame = parseSseFrame(frameText);
          if (frame && await onEvent(frame)) {
            stoppedEarly = true;
            return;
          }
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) throw new Error("AI 스트리밍 응답이 완전히 끝나지 않았습니다.");
    } finally {
      if (!reachedEof || stoppedEarly) {
        try { await reader.cancel(); } catch (_) { /* no-op */ }
      }
      reader.releaseLock();
    }
  }

  async function requestCompleted(payload, signal) {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload),
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
    const data = await response.json().catch(() => null);
    if (!response.ok || !data) {
      throw errorFor(data, "AI 작업을 처리하지 못했습니다. 다시 시도해 주세요.");
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
    const done = `event: done\ndata: ${JSON.stringify(donePayload)}\n\n`;
    return new Response(delta + done, {
      status: 200,
      headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  async function tryOrchestration(payload, signal) {
    if (!await orchestrationReady(signal)) return null;
    let data;
    try {
      data = await postOrchestration("/api/orchestration", payload, signal);
    } catch (error) {
      if (error && error.code === "orchestration_not_applicable") return null;
      throw error;
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

  async function requestStreaming(payload, signal) {
    const orchestrated = await tryOrchestration(payload, signal);
    if (orchestrated) return orchestrated;

    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(payload),
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
    errorFor,
    parseSseFrame,
    readSseEvents,
    requestCompleted,
    requestStreaming,
    orchestrationReady,
    resumeOrchestration,
    cancelOrchestration,
    setOrchestrationPauseHandler,
  });
})();