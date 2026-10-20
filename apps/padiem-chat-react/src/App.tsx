import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { ClawWorkspace } from "./components/ClawWorkspace";
import { Composer } from "./components/Composer";
import { ConversationView } from "./components/ConversationView";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import {
  CONNECTOR_CARDS,
  FIXTURE_FAILURE_TRIGGER,
  MODEL_CHOICES,
  createFixtureConversations,
  pickFixtureReply,
} from "./data/fixtures";
import type { ChatMessage, ConnectorId } from "./data/types";
import {
  chatReducer,
  initialChatState,
  selectActiveConversation,
  selectVisibleConversations,
} from "./state/chatStore";
import { mountOperationalGlassShell } from "./lib/glass-shell";
import {
  applyTheme,
  readThemeAttributes,
  themeSearch,
  type ThemeAttributes,
} from "./theme/theme";

/** How long the fixture answer takes to arrive. Long enough to show the loading state. */
const FIXTURE_LATENCY_MS = 450;

let idCounter = 0;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}_${Date.now().toString(36)}_${idCounter}`;
}

/**
 * #5298 — React clone root.
 *
 * The shell reproduces the operational product's structure and state contract
 * (`data-state`, `sidebar-collapsed`, `sidebar-open`) so the operational
 * stylesheets render the clone exactly as they render the product.
 *
 * Answers come from local fixtures. No auth, no backend, no live model call.
 */
export function App() {
  const [themeAttributes, setThemeAttributes] = useState<ThemeAttributes>(() =>
    readThemeAttributes(typeof window === "undefined" ? "" : window.location.search),
  );
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const [state, dispatch] = useReducer(
    chatReducer,
    undefined,
    () =>
      initialChatState(
        createFixtureConversations(),
        MODEL_CHOICES,
        CONNECTOR_CARDS.map((card) => ({ ...card })),
      ),
  );

  useEffect(() => {
    applyTheme(themeAttributes);
  }, [themeAttributes]);

  // The glass theme paints its portrait and shell ribbons from the
  // operational module. It installs against the mounted shell, so it is loaded
  // after the first render.
  useEffect(() => {
    void mountOperationalGlassShell().catch(() => {
      /* The clone still renders without the decorative glass layer. */
    });
  }, []);

  const activeConversation = selectActiveConversation(state);
  const visibleConversations = selectVisibleConversations(state);

  const handleSelectTheme = useCallback((theme: ThemeAttributes["theme"]) => {
    setThemeAttributes((current) => {
      const next: ThemeAttributes = { ...current, theme };
      if (typeof window !== "undefined") {
        const search = themeSearch(next);
        window.history.replaceState(
          window.history.state,
          "",
          `${window.location.pathname}${search}${window.location.hash}`,
        );
      }
      return next;
    });
  }, []);

  const handleNewChat = useCallback(() => {
    dispatch({
      type: "create-conversation",
      conversationId: nextId("chat"),
      title: "새 대화",
    });
    setMobileOpen(false);
  }, []);

  const handleSend = useCallback(
    (prompt: string) => {
      const conversationId = activeConversation?.id ?? nextId("chat");
      if (!activeConversation) {
        dispatch({
          type: "create-conversation",
          conversationId,
          title: "새 대화",
        });
      }
      const now = new Date().toISOString();
      const userMessage: ChatMessage = {
        id: nextId("msg_user"),
        role: "user",
        content: prompt,
        completedAt: now,
        state: "complete",
        errorMessage: null,
        sourcePrompt: prompt,
        attempt: 1,
        fixture: false,
      };
      const assistantMessage: ChatMessage = {
        id: nextId("msg_assistant"),
        role: "assistant",
        content: "",
        completedAt: null,
        state: "streaming",
        errorMessage: null,
        sourcePrompt: prompt,
        attempt: 1,
        fixture: true,
      };
      dispatch({ type: "send-message", conversationId, userMessage, assistantMessage, prompt });
      dispatch({ type: "clear-attachment" });
    },
    [activeConversation],
  );

  const handleRetry = useCallback(
    (messageId: string) => {
      if (!activeConversation) return;
      dispatch({
        type: "retry-message",
        conversationId: activeConversation.id,
        messageId,
      });
    },
    [activeConversation],
  );

  const handleOpenConnector = useCallback((connectorId: ConnectorId) => {
    dispatch({
      type: "set-connector-state",
      connectorId,
      state: "unknown",
    });
  }, []);

  const handleAttach = useCallback((file: File) => {
    const sizeLabel = file.size >= 1024 * 1024
      ? `${(file.size / (1024 * 1024)).toFixed(1)}MB`
      : `${Math.max(1, Math.round(file.size / 1024))}KB`;
    dispatch({
      type: "attach-file",
      attachment: {
        id: nextId("attachment"),
        name: file.name,
        sizeLabel,
        kind: file.type.startsWith("image/") ? "image" : "document",
      },
    });
  }, []);

  // The fixture answer replaces the loading turn once the simulated latency is
  // over. The failure trigger keeps the error and retry states reachable.
  useEffect(() => {
    const pending = state.pendingTurn;
    if (!pending) return;
    const timer = window.setTimeout(() => {
      // The failure trigger only fails the first attempt, so the retry path is
      // a real recovery instead of a loop.
      if (pending.attempt === 1 && pending.prompt.includes(FIXTURE_FAILURE_TRIGGER)) {
        dispatch({
          type: "fail-message",
          conversationId: pending.conversationId,
          messageId: pending.messageId,
          errorMessage: "fixture 응답을 생성하지 못했습니다. 다시 시도해 주세요.",
        });
        return;
      }
      const reply = pickFixtureReply(pending.prompt);
      dispatch({
        type: "resolve-message",
        conversationId: pending.conversationId,
        messageId: pending.messageId,
        content: reply.body,
        completedAt: new Date().toISOString(),
      });
    }, FIXTURE_LATENCY_MS);
    return () => window.clearTimeout(timer);
  }, [state.pendingTurn]);

  // The operational product publishes the shell state: "home" on the empty
  // first screen, "chat" once a conversation is active and "claw" in the Claw
  // product. The stylesheets select on it, so the clone keeps the same names.
  const shellState = useMemo<string>(() => {
    if (state.mode === "claw") return "claw";
    const hasTurns = (activeConversation?.messages.length ?? 0) > 0;
    return hasTurns ? "chat" : "home";
  }, [state.mode, activeConversation]);

  return (
    <div
      className={[
        "app-shell",
        "clone-app-shell",
        collapsed ? "sidebar-collapsed" : "",
        mobileOpen ? "sidebar-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-state={shellState}
    >
      <Sidebar
        mode={state.mode}
        conversations={state.conversations}
        visibleConversations={visibleConversations}
        activeConversationId={state.activeConversationId}
        searchQuery={state.searchQuery}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onNewChat={handleNewChat}
        onSelectConversation={(conversationId) => {
          dispatch({ type: "select-conversation", conversationId });
          setMobileOpen(false);
        }}
        onDeleteConversation={(conversationId) =>
          dispatch({ type: "delete-conversation", conversationId })
        }
        onSearchQuery={(query) => dispatch({ type: "set-search-query", query })}
        onToggleCollapse={() => setCollapsed((value) => !value)}
        onCloseMobile={() => setMobileOpen(false)}
        onOpenMode={(mode) => dispatch({ type: "set-mode", mode })}
      />
      <div
        className="sidebar-scrim"
        id="sidebarScrim"
        hidden={!mobileOpen}
        onClick={() => setMobileOpen(false)}
      />
      <main className="main-panel">
        <TopBar
          theme={themeAttributes.theme}
          collapsed={collapsed}
          onSelectTheme={handleSelectTheme}
          onOpenMobile={() => setMobileOpen(true)}
          onRestoreSidebar={() => setCollapsed(false)}
        />
        <ClawWorkspace visible={state.mode === "claw"} />
        <ConversationView
          conversation={activeConversation}
          mode={state.mode}
          connectors={state.connectors}
          onPrompt={handleSend}
          onOpenConnector={handleOpenConnector}
          onRetry={handleRetry}
        />
        <Composer
          modelChoices={state.modelChoices}
          selectedModelId={state.modelId}
          pendingAttachment={state.pendingAttachment}
          streaming={state.pendingTurn !== null}
          pcState={state.connectors.find((card) => card.id === "pc")?.state ?? "unknown"}
          onSelectModel={(modelId) => dispatch({ type: "set-model", modelId })}
          onSend={handleSend}
          onAttach={handleAttach}
          onClearAttachment={() => dispatch({ type: "clear-attachment" })}
          onRefreshPcState={() =>
            dispatch({ type: "set-connector-state", connectorId: "pc", state: "unknown" })
          }
          onConnectPc={() => handleOpenConnector("pc")}
        />
      </main>
    </div>
  );
}
