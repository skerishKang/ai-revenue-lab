import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../App";

/**
 * #5298 — composer behaviour.
 *
 * The send path, the loading state, the fixture answer, the error state and
 * the retry are all reachable from the first screen. Nothing here claims a
 * live API answer: every answer is produced by the local fixture source.
 */
describe("React clone composer", () => {
  it("sends a turn and shows the fixture answer", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = document.getElementById("messageInput") as HTMLTextAreaElement;
    await user.type(input, "견적서 초안을 준비해줘");
    await user.click(document.getElementById("sendButton") as HTMLElement);

    await waitFor(
      () => {
        expect(screen.getByText("견적서 초안을 준비해줘")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    await waitFor(
      () => {
        expect(document.getElementById("messageList")).not.toHaveAttribute("hidden");
        expect(screen.getByText(/이 복제본은 실제 백엔드에 연결되어 있지 않아/)).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("submits on Enter but not on Shift+Enter", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = document.getElementById("messageInput") as HTMLTextAreaElement;
    await user.type(input, "첫 줄{Shift>}{Enter}{/Shift}둘째 줄");
    expect(input.value).toContain("둘째 줄");
    // Shift+Enter must not send the turn.
    expect(document.getElementById("messageList")).toHaveAttribute("hidden");

    await user.type(input, "{Enter}");
    await waitFor(
      () => {
        expect(document.getElementById("messageList")).not.toHaveAttribute("hidden");
        expect(
          document.querySelector(".user-message .message-bubble")?.textContent,
        ).toContain("첫 줄");
      },
      { timeout: 3000 },
    );
  });

  it("shows the error state and recovers through retry", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = document.getElementById("messageInput") as HTMLTextAreaElement;
    // "[[" types a literal "[" in user-event's key syntax.
    await user.type(input, "[[오류] 실패 요청");
    await user.click(document.getElementById("sendButton") as HTMLElement);

    await waitFor(
      () => {
        expect(screen.getByText("fixture 응답을 생성하지 못했습니다. 다시 시도해 주세요.")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    await user.click(screen.getByRole("button", { name: "다시 시도" }));

    await waitFor(
      () => {
        expect(
          screen.queryByText("fixture 응답을 생성하지 못했습니다. 다시 시도해 주세요."),
        ).not.toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("selects a model from the model picker", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "AI 등급" }));
    await user.click(screen.getByRole("option", { name: /고성능 모델/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "AI 등급" })).toHaveTextContent("고성능 모델");
    });
  });

  it("shows and removes a pending attachment", async () => {
    const user = userEvent.setup();
    render(<App />);

    const fileInput = document.getElementById("attachmentFileInput") as HTMLInputElement;
    await user.upload(fileInput, new File(["clone"], "report.txt", { type: "text/plain" }));

    await waitFor(() => {
      expect(document.getElementById("attachmentTray")).not.toHaveAttribute("hidden");
      expect(document.getElementById("attachmentName")).toHaveTextContent("report.txt");
    });

    await user.click(screen.getByRole("button", { name: "첨부 파일 제거" }));

    await waitFor(() => {
      expect(document.getElementById("attachmentTray")).toHaveAttribute("hidden");
    });
  });

  it("shows the computer connection status without claiming a connection", async () => {
    const user = userEvent.setup();
    render(<App />);

    const status = document.getElementById("composerPcStatus");
    expect(status).toBeInTheDocument();
    expect(status).toHaveAttribute("data-state", "unknown");
    expect(status?.querySelector(".composer-pc-status-label")).toHaveTextContent(
      "컴퓨터 연결",
    );
    // The composer reserves the measured text gutter for the control.
    expect(document.getElementById("composerForm")).toHaveAttribute("data-pc-status", "ready");

    // The control opens the existing computer connection surface.
    await user.click(status as HTMLElement);
    await waitFor(() => {
      expect(document.getElementById("clawDeviceManagerPanel")).not.toHaveAttribute("hidden");
    });
  });
});
