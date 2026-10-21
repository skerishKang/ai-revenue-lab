import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

/**
 * #5298 — the sign-in path.
 *
 * The clone has no authentication of its own. The dialog posts to the
 * operational password route and the operational session cookie decides the
 * rest, so the test asserts the route, the payload and the follow-up read.
 */
describe("React clone sign-in path", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "content-type": "application/json" },
        });
      if (url.includes("/api/auth/password/login")) {
        return json(
          { error: { code: "invalid_credentials", message: "로그인 정보를 확인해 주세요." } },
          401,
        );
      }
      if (url.includes("/api/auth/status")) {
        return json({
          ready: true,
          authenticated: false,
          history_ready: true,
          user: null,
          model_requires_session: true,
          session_state: "guest",
          methods: { password: true },
        });
      }
      if (url.includes("/api/conversations")) {
        return json({ error: { code: "unauthorized", message: "로그인이 필요합니다." } }, 401);
      }
      return json({ error: { code: "not_found", message: "not found" } }, 404);
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("posts the operational password payload and shows the server's refusal", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });

    await user.click(document.getElementById("loginButton") as HTMLElement);
    await user.type(screen.getByLabelText("아이디 또는 이메일"), "clone@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "wrong-password");
    await user.click(document.getElementById("passwordLoginSubmit") as HTMLElement);

    await waitFor(() => {
      expect(screen.getByText("로그인 정보를 확인해 주세요.")).toBeInTheDocument();
    });

    const loginCall = (globalThis.fetch as unknown as { mock: { calls: [RequestInfo | URL, RequestInit | undefined][] } }).mock.calls.find(
      (call) => String(call[0]).includes("/api/auth/password/login"),
    );
    expect(loginCall).toBeTruthy();
    expect(loginCall?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(loginCall?.[1]?.body))).toEqual({
      identifier: "clone@example.com",
      password: "wrong-password",
    });
  });
});
