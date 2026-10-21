import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

/**
 * #5298 — the conversation contract.
 *
 * The clone reads and deletes conversations through the operational routes. The
 * paths, the methods and the response checks are the ones
 * `apps/padiem-chat/app/conversation_routes.py` serves.
 */

const CONVERSATION_ID = "chat_0123456789abcdef0123456789abcdef";

interface Recorded {
  url: string;
  method: string;
}

function installFetch(conversationDeleted: { value: boolean }) {
  const calls: Recorded[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      });

    if (url.includes("/api/auth/status")) {
      return json({
        ready: true,
        authenticated: true,
        history_ready: true,
        user: { id: "usr_test" },
        model_requires_session: false,
        session_state: "active",
        methods: { password: true },
      });
    }
    if (url.includes("/api/orchestration/status")) {
      return json({ orchestration_ready: false, authenticated: true });
    }
    if (method === "DELETE" && url.includes(`/api/conversations/${CONVERSATION_ID}`)) {
      if (!conversationDeleted.value) return json({ deleted: false }, 409);
      conversationDeleted.value = true;
      return json({ deleted: true, conversation_id: CONVERSATION_ID });
    }
    if (method === "GET" && url.includes(`/api/conversations/${CONVERSATION_ID}`)) {
      return json({
        conversation: {
          id: CONVERSATION_ID,
          title: "실제 대화",
          messages: [
            { role: "user", content: "이전 대화입니다" },
            { role: "assistant", content: "이전 답변입니다" },
          ],
        },
      });
    }
    if (url.includes("/api/conversations")) {
      return json({
        conversations: [
          { id: CONVERSATION_ID, title: "실제 대화", updated_at: "2026-10-21T10:00:00Z" },
        ],
      });
    }
    return json({ error: { code: "not_found", message: "not found" } }, 404);
  }) as typeof fetch;
  return calls;
}

describe("React clone conversation contract", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    installFetch({ value: false });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("opens a saved conversation through the detail route and renders its turns", async () => {
    const user = userEvent.setup();
    const calls = installFetch({ value: false });
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 대화")).toBeInTheDocument();
    });

    await user.click(screen.getByText("실제 대화"));

    await waitFor(() => {
      expect(screen.getByText("이전 대화입니다")).toBeInTheDocument();
    });
    expect(screen.getByText("이전 답변입니다")).toBeInTheDocument();

    const detailCall = calls.find((call) => call.url.includes(`/api/conversations/${CONVERSATION_ID}`));
    expect(detailCall?.method).toBe("GET");
  });

  it("deletes a saved conversation through the delete route", async () => {
    const user = userEvent.setup();
    const calls = installFetch({ value: false });
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 대화")).toBeInTheDocument();
    });

    await user.click(document.querySelector("summary.history-more") as HTMLElement);
    await user.click(screen.getByRole("button", { name: /대화 삭제/ }));

    await waitFor(() => {
      const deleteCall = calls.find((call) => call.method === "DELETE");
      expect(deleteCall).toBeTruthy();
      expect(deleteCall?.url).toContain(`/api/conversations/${CONVERSATION_ID}`);
    });
  });
});
