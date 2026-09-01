(() => {
  "use strict";

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

  async function requestStreaming(payload, signal) {
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
  });
})();