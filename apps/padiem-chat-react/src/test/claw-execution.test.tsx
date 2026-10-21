import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

/**
 * #5298 — the Claw execution lane.
 *
 * The request contract, the canonical P01 event projection, the recovery truth
 * and the approval intents all come from the operational modules. Only the
 * network is replaced, so the endpoints, the payload, the event validation and
 * the intent bodies are the ones the product uses.
 */

const RUN = {
  event_id: "evt_1",
  run_id: "run_1",
  trace_id: "trace_1",
  app_id: "app_1",
  timestamp_iso: "2026-10-21T10:00:00.000Z",
};

function sse(frames: string[]): Response {
  return new Response(`${frames.join("\n\n")}\n\n`, {
    status: 200,
    headers: { "content-type": "text/event-stream; charset=utf-8" },
  });
}

describe("React clone Claw execution lane", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
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
      if (url.includes("/api/conversations")) {
        return json({ conversations: [] });
      }
      if (url.includes("/api/claw/general/capabilities")) {
        return json({ live_events_available: false });
      }
      if (url.includes("/api/claw/local-access/devices")) {
        return json({
          read_completed: true,
          available: true,
          status_code: "ok",
          devices: [
            { device_id: "pc_1", name: "작업 PC", platform: "windows", online: true },
          ],
          saved_target_id: null,
        });
      }
      if (url.includes("/api/claw/general") && method === "POST") {
        return sse([
          `event: p01_event\ndata: ${JSON.stringify({ ...RUN, kind: "run_started", sequence: 1, delivery: "live" })}`,
          `event: p01_event\ndata: ${JSON.stringify({ ...RUN, kind: "tool_started", sequence: 2, delivery: "live" })}`,
          'event: delta\ndata: {"delta":"컴퓨터에서 작업을 실행했습니다."}',
          'event: done\ndata: {"done":true}',
        ]);
      }
      return json({ error: { code: "not_found", message: "not found" } }, 404);
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("runs the Claw lane and shows the canonical P01 runtime label", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Claw" }));

    const input = document.getElementById("messageInput") as HTMLTextAreaElement;
    await user.type(input, "내 컴퓨터에서 파일을 정리해줘");
    await user.click(document.getElementById("sendButton") as HTMLElement);

    await waitFor(
      () => {
        expect(
          document.querySelector(".assistant-message .assistant-content")?.textContent,
        ).toContain("컴퓨터에서 작업을 실행했습니다.");
      },
      { timeout: 5000 },
    );

    // Only a validated canonical P01 envelope may set the runtime label.
    const label = document.querySelector(".assistant-message [data-runtime-label]");
    expect(label?.textContent).toBe("도구가 실행 중입니다");

    const calls = (globalThis.fetch as unknown as {
      mock: { calls: [RequestInfo | URL, RequestInit | undefined][] };
    }).mock.calls;
    const clawCall = calls.find(
      (call) =>
        String(call[0]).includes("/api/claw/general") &&
        !String(call[0]).includes("capabilities"),
    );
    expect(clawCall).toBeTruthy();
    expect(clawCall?.[1]?.method).toBe("POST");
    const body = JSON.parse(String(clawCall?.[1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      mode: "auto",
      messages: [{ role: "user", content: "내 컴퓨터에서 파일을 정리해줘" }],
    });
  });

  it("shows the server-reported computer list", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Claw" }));

    await waitFor(() => {
      expect(screen.getByText("작업 PC")).toBeInTheDocument();
    });
  });
});
