import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

/**
 * #5298 — the Claw approval pause.
 *
 * A run that needs a decision pauses. The browser only sends an intent, and
 * the intent body is built by the operational orchestration module, so the
 * continuation reference, the pause id and the outcome are the product's own.
 */
const CONTINUATION_REF = "cont_0123456789abcdef";
const PAUSE_ID = "pause_1";

const ORCHESTRATION = {
  events: [
    {
      kind: "run_started",
      sequence: 1,
      event_id: "evt_1",
      run_id: "run_1",
      trace_id: "trace_1",
      app_id: "app_1",
    },
    {
      kind: "approval_paused",
      sequence: 2,
      event_id: "evt_2",
      run_id: "run_1",
      trace_id: "trace_1",
      app_id: "app_1",
    },
  ],
  continuation_ref: CONTINUATION_REF,
  approval_pause: {
    status: "paused",
    continuation_id: PAUSE_ID,
    requirement: "user_confirmation",
    expires_at: "2026-10-21T11:00:00.000Z",
  },
};

describe("React clone Claw approval pause", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
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
      if (url.includes("/api/conversations")) return json({ conversations: [] });
      if (url.includes("/api/orchestration/status")) {
        return json({ orchestration_ready: true, authenticated: true });
      }
      if (url.includes("/api/orchestration/resume")) {
        return json({ answer: "승인 후 실행을 마쳤습니다." });
      }
      if (url.includes("/api/orchestration")) {
        return json({ orchestration: ORCHESTRATION, answer: "" });
      }
      if (url.includes("/api/chat/stream")) {
        return new Response("", { status: 200, headers: { "content-type": "text/event-stream" } });
      }
      return json({ error: { code: "not_found", message: "not found" } }, 404);
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("pauses for a decision and resumes with the operational intent", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });

    const input = document.getElementById("messageInput") as HTMLTextAreaElement;
    await user.type(input, "파일을 정리해줘");
    await user.click(document.getElementById("sendButton") as HTMLElement);

    await waitFor(() => {
      expect(screen.getByText("계속하기 전에 확인이 필요합니다.")).toBeInTheDocument();
    });

    await user.click(document.getElementById("clawApprovalApprove") as HTMLElement);

    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as {
        mock: { calls: [RequestInfo | URL, RequestInit | undefined][] };
      }).mock.calls;
      const resume = calls.find((call) => String(call[0]).includes("/api/orchestration/resume"));
      expect(resume).toBeTruthy();
      const body = JSON.parse(String(resume?.[1]?.body)) as Record<string, unknown>;
      // The intent body comes from the operational orchestration module.
      expect(body).toMatchObject({
        continuationRef: CONTINUATION_REF,
        pauseId: PAUSE_ID,
        outcome: "approved",
        requiresTrustedDecision: true,
      });
    });

    await waitFor(() => {
      expect(
        document.querySelector(".assistant-message .assistant-content")?.textContent,
      ).toContain("승인 후 실행을 마쳤습니다.");
    });
  });
});
