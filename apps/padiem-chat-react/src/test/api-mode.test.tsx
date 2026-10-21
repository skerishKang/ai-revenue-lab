import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

/**
 * #5298 — the real API path.
 *
 * The test uses the operational transport module and its real SSE frame
 * reader. Only the network is replaced, so the request path, the payload, the
 * event names and the rendered turns are the ones the product uses.
 */

const CONVERSATION_ID = "chat_0123456789abcdef0123456789abcdef";

const SSE_BODY = [
  'event: delta',
  'data: {"delta":"실제 API 응답입니다."}',
  "",
  'event: delta',
  'data: {"delta":" 두 번째 조각."}',
  "",
  "event: done",
  `data: {"done":true,"conversation_id":"${CONVERSATION_ID}"}`,
  "",
  "",
].join("\n");

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("React clone against the real Chat API path", () => {
  const originalFetch = globalThis.fetch;
  let calls: { url: string; method: string; body: unknown }[] = [];

  beforeEach(() => {
    calls = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      let body: unknown = null;
      if (typeof init?.body === "string") {
        try {
          body = JSON.parse(init.body);
        } catch {
          body = init.body;
        }
      }
      calls.push({ url, method, body });

      if (url.includes("/api/auth/status")) {
        return jsonResponse({
          ready: true,
          authenticated: true,
          history_ready: true,
          user: { id: "usr_test" },
          model_requires_session: false,
          session_state: "active",
          methods: { google: true, password: true },
        });
      }
      if (url.includes("/api/orchestration/status")) {
        return jsonResponse({ orchestration_ready: false, authenticated: true });
      }
      if (url.includes("/api/conversations") && method === "GET" && !url.includes("/api/conversations/")) {
        return jsonResponse({
          conversations: [{ id: CONVERSATION_ID, title: "실제 대화", updated_at: "2026-10-21T10:00:00Z" }],
        });
      }
      if (url.includes("/api/chat/stream")) {
        return new Response(SSE_BODY, {
          status: 200,
          headers: { "content-type": "text/event-stream; charset=utf-8" },
        });
      }
      return jsonResponse({ error: { code: "not_found", message: "not found" } }, 404);
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("shows the API badge and the server-owned conversation list", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText("실제 대화")).toBeInTheDocument();
    });
    // The fixture conversation list is replaced by the server's list.
    expect(screen.queryByText("주간 일정 정리")).not.toBeInTheDocument();
  });

  it("streams a real answer through the operational transport", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });

    const input = document.getElementById("messageInput") as HTMLTextAreaElement;
    await user.type(input, "실제 API에 연결해줘");
    await user.click(document.getElementById("sendButton") as HTMLElement);

    await waitFor(
      () => {
        expect(
          document.querySelector(".assistant-message .assistant-content")?.textContent,
        ).toContain("실제 API 응답입니다.");
      },
      { timeout: 5000 },
    );

    // The answer carries no fixture label: it came from the API.
    expect(
      document.querySelector(".assistant-message .demo-label")?.textContent ?? "",
    ).not.toContain("fixture");

    const streamCall = calls.find((call) => call.url.includes("/api/chat/stream"));
    expect(streamCall).toBeTruthy();
    expect(streamCall?.method).toBe("POST");
    // The operational Chat payload: the outbound messages and the automatic
    // mode. The account tier is never claimed by the clone.
    expect(streamCall?.body).toMatchObject({
      mode: "auto",
      messages: [{ role: "user", content: "실제 API에 연결해줘" }],
    });
    expect((streamCall?.body as Record<string, unknown>).tier).toBeUndefined();
  });

  it("keeps the offline badge when the API does not answer", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("network down");
    }) as typeof fetch;

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("복제본 미리보기")).toBeInTheDocument();
    });
  });
});
