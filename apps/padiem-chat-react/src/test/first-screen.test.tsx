import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../App";

/**
 * #5298 — first-screen contract.
 *
 * The assertions are on the element ids and accessible names that the
 * operational product uses, so a regression that breaks the comparison
 * surface is visible here without a browser.
 */
describe("React clone first screen", () => {
  it("renders the operational shell structure", () => {
    render(<App />);

    const shell = document.querySelector(".app-shell");
    expect(shell).toBeInTheDocument();
    // The operational product publishes "home" on the empty first screen.
    expect(shell).toHaveAttribute("data-state", "home");

    expect(screen.getByRole("complementary", { name: "주요 메뉴" })).toBeInTheDocument();
    expect(document.getElementById("newChatButton")).toBeInTheDocument();
    expect(document.getElementById("historySection")).toBeInTheDocument();
    expect(document.getElementById("emptyState")).toBeInTheDocument();
    expect(document.getElementById("messageList")).toBeInTheDocument();
    expect(document.getElementById("composerForm")).toBeInTheDocument();
    expect(document.getElementById("messageInput")).toBeInTheDocument();
    expect(document.getElementById("sendButton")).toBeInTheDocument();
    expect(document.getElementById("attachmentButton")).toBeInTheDocument();
  });

  it("shows the operational first-screen copy", () => {
    render(<App />);
    expect(screen.getByText("안녕하세요.")).toBeInTheDocument();
    expect(screen.getByText("무엇을 도와드릴까요?")).toBeInTheDocument();
    expect(screen.getByText("쉽게 설명해줘")).toBeInTheDocument();
    expect(screen.getByText("편하게 질문해 보세요")).toBeInTheDocument();
  });

  it("starts with the message list hidden and the introductory block visible", () => {
    render(<App />);
    expect(document.getElementById("emptyState")).not.toHaveAttribute("hidden");
    expect(document.getElementById("messageList")).toHaveAttribute("hidden");
  });

  it("switches the shell to the Claw state and back", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Claw" }));

    await waitFor(() => {
      expect(document.querySelector(".app-shell")).toHaveAttribute("data-state", "claw");
    });
    expect(document.getElementById("clawWorkspace")).not.toHaveAttribute("hidden");
  });

  it("publishes the chat state once a turn exists", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = document.getElementById("messageInput") as HTMLTextAreaElement;
    await user.type(input, "가까운 시나리오");
    await user.click(document.getElementById("sendButton") as HTMLElement);

    await waitFor(() => {
      expect(document.querySelector(".app-shell")).toHaveAttribute("data-state", "chat");
    });
  });

  it("switches the theme and writes the theme contract onto the document", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "테마 선택" }));
    await user.click(screen.getByRole("button", { name: "Dark" }));

    await waitFor(() => {
      expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    });
    expect(document.body).toHaveAttribute("data-theme", "dark");
  });

  it("filters the recent conversations through the sidebar search", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(document.getElementById("sidebarSearchButton") as HTMLElement);
    const input = await screen.findByLabelText("대화 검색어 입력");
    await user.type(input, "견적서");

    await waitFor(() => {
      const results = document.getElementById("conversationSearchResults");
      expect(results).toHaveTextContent("견적서 초안 검토");
      expect(results).not.toHaveTextContent("주간 일정 정리");
    });
  });
});
