import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

/**
 * #5298 — the workspace views.
 *
 * The library, the automation, the calendar and the meeting notes read the
 * product's own routes. The tests assert the routes, the responses and the
 * states the product already defines: loading, empty and error.
 */
describe("React clone workspace views", () => {
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
      if (url.includes("/api/conversations")) return json({ conversations: [] });
      if (url.includes("/api/project-files")) {
        return json({
          files: [
            { id: "file_1", name: "계약서.pdf", project_id: "proj_1", media_type: "application/pdf" },
          { id: "file_2", name: "메모.txt", project_id: "proj_1", media_type: "text/plain" },
          ],
          has_more: false,
          next_cursor: null,
        });
      }
      if (url.includes("/api/claw/automation/rules")) {
        if (method === "POST") {
          return json(
            {
              ok: true,
              rule: {
                rule_id: "rule_new",
                name: "매일 요약",
                schedule_expression: "09:00",
                schedule_timezone: "Asia/Seoul",
                enabled: true,
              },
            },
            201,
          );
        }
        return json({
          ok: true,
          rules: [
            {
              rule_id: "rule_1",
              name: "매일 요약",
              schedule_expression: "09:00",
              schedule_timezone: "Asia/Seoul",
              enabled: true,
            },
          ],
          truncated: false,
        });
      }
      if (url.includes("/api/calendar/today")) {
        return json({ items: [{ calendar_item_id: "cal_1", title: "팀 미팅", date: "2026-10-21" }] });
      }
      if (url.includes("/api/claw/meetings")) {
        return json({ meetings: [{ meeting_ref: "meet_1", title: "10월 정기 회의" }] });
      }
      return json({ error: { code: "not_found", message: "not found" } }, 404);
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("renders the library from the owner's file route", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });

    await user.click(document.getElementById("filesNavButton") as HTMLElement);

    await waitFor(() => {
      expect(screen.getByText("계약서.pdf")).toBeInTheDocument();
    });
    expect(screen.getByText("메모.txt")).toBeInTheDocument();

    const calls = (globalThis.fetch as unknown as {
      mock: { calls: [RequestInfo | URL, RequestInit | undefined][] };
    }).mock.calls;
    expect(calls.some((call) => String(call[0]).includes("/api/project-files"))).toBe(true);
  });

  it("renders the automation rules and creates one through the product's route", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });

    await user.click(document.getElementById("automationNavButton") as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText("매일 요약")).toBeInTheDocument();
    });

    await user.type(document.getElementById("clawAutomationCreateName") as HTMLElement, "주간 보고");
    await user.type(
      document.getElementById("clawAutomationCreateExpression") as HTMLElement,
      "09:00",
    );
    await user.type(
      document.getElementById("clawAutomationCreateTimezone") as HTMLElement,
      "Asia/Seoul",
    );
    await user.click(document.getElementById("clawAutomationCreateSubmit") as HTMLElement);

    await waitFor(() => {
      const calls = (globalThis.fetch as unknown as {
        mock: { calls: [RequestInfo | URL, RequestInit | undefined][] };
      }).mock.calls;
      const create = calls.find(
        (call) => String(call[0]).includes("/api/claw/automation/rules") && call[1]?.method === "POST",
      );
      expect(create).toBeTruthy();
      expect(JSON.parse(String(create?.[1]?.body))).toMatchObject({
        name: "주간 보고",
        schedule_expression: "09:00",
        schedule_timezone: "Asia/Seoul",
      });
    });
  });

  it("renders the calendar and the meeting notes", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });

    await user.click(document.getElementById("calendarNavButton") as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText("팀 미팅")).toBeInTheDocument();
    });
    // The tab contract is the product's.
    expect(document.getElementById("calendarMonthTab")).toBeInTheDocument();
    expect(document.getElementById("calendarTodayTab")).toBeInTheDocument();

    await user.click(document.getElementById("meetingNavButton") as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText("10월 정기 회의")).toBeInTheDocument();
    });
  });

  it("shows the error state when a workspace route refuses", async () => {
    const user = userEvent.setup();
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
          user: null,
          model_requires_session: false,
          session_state: "active",
          methods: {},
        });
      }
      if (url.includes("/api/conversations")) return json({ conversations: [] });
      if (url.includes("/api/project-files")) {
        return json(
          { error: { code: "project_files_unavailable", message: "프로젝트 파일을 현재 사용할 수 없습니다." } },
          503,
        );
      }
      return json({ error: { code: "not_found" } }, 404);
    }) as typeof fetch;

    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("실제 API 연결")).toBeInTheDocument();
    });
    await user.click(document.getElementById("filesNavButton") as HTMLElement);

    await waitFor(() => {
      expect(screen.getByText("프로젝트 파일을 현재 사용할 수 없습니다.")).toBeInTheDocument();
    });
  });
});
