import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TRANSPORT_JS = fs.readFileSync(
  path.join(__dirname, "..", "static", "chat-transport.js"),
  "utf8",
);

function makeNdjsonResponse(lines) {
  const encoded = new TextEncoder().encode(lines.map((item) => JSON.stringify(item)).join("\n") + "\n");
  let consumed = false;
  return {
    ok: true,
    status: 200,
    headers: {
      get(name) {
        if (String(name).toLowerCase() === "content-type") return "application/x-ndjson";
        return null;
      },
    },
    body: {
      getReader() {
        return {
          async read() {
            if (consumed) return { done: true, value: undefined };
            consumed = true;
            return { done: false, value: encoded };
          },
          async cancel() {},
          releaseLock() {},
        };
      },
    },
  };
}

test("#7459: NDJSON orchestration_pause triggers pause handler instead of falling through to error", async () => {
  const pausePayload = {
    events: [
      {
        event_id: "evt_1",
        run_id: "run_1",
        trace_id: "trace_1",
        app_id: "padiem-chat",
        kind: "approval_paused",
        sequence: 1,
      },
    ],
    approval_pause: {
      status: "paused",
      continuation_id: "pause_7459",
      requirement: "user_confirmation",
      expires_at: "2099-01-01T00:00:00Z",
    },
    continuation_ref: "cont_7459_pause_ref",
    answer: null,
  };

  const ndjsonResponse = makeNdjsonResponse([
    { type: "meta", stream: true },
    { type: "progress", kind: "tool_started", sequence: 1, label: "PC 작업 중" },
    { type: "orchestration_pause", orchestration: pausePayload },
  ]);

  const context = {
    window: {},
    TextDecoder,
    TextEncoder,
    Date,
    setTimeout,
    clearTimeout,
    fetch: async (url) => {
      if (url === "/api/orchestration/status") {
        return {
          ok: true,
          status: 200,
          headers: { get: () => "application/json" },
          json: async () => ({ orchestration_ready: true, authenticated: true }),
        };
      }
      if (url === "/api/orchestration") {
        return ndjsonResponse;
      }
      throw new Error("unexpected url: " + url);
    },
  };
  context.window = context;
  vm.runInNewContext(TRANSPORT_JS, context);

  const transport = context.PadiemChatTransport;
  const pausedNotifications = [];
  transport.setOrchestrationPauseHandler((info) => {
    pausedNotifications.push(info);
  });

  const requestBody = { messages: [{ role: "user", content: "파일 수정해줘" }], tier: "max" };
  const response = await transport.requestOrchestrationStream(requestBody, undefined, false);
  assert.equal(response, ndjsonResponse);

  const seenFrames = [];
  await assert.rejects(
    async () => {
      await transport.readSseEvents(response, async (frame) => {
        seenFrames.push(frame.event);
        return false;
      });
    },
    (err) => err && err.name === "AbortError" && err.message === "approval paused",
  );

  assert.deepEqual(seenFrames, ["meta", "progress"]);
  assert.equal(pausedNotifications.length, 1);
  assert.equal(
    pausedNotifications[0].orchestration.approval_pause.continuation_id,
    "pause_7459",
  );
  assert.deepEqual(pausedNotifications[0].requestPayload, requestBody);
});
