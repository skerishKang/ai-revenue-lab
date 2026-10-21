import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { ClawWorkspace } from "./components/ClawWorkspace";
import { Composer } from "./components/Composer";
import { ConversationView } from "./components/ConversationView";
import { LoginDialog } from "./components/LoginDialog";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import {
  CONNECTOR_CARDS,
  FIXTURE_FAILURE_TRIGGER,
  MODEL_CHOICES,
  createFixtureConversations,
  pickFixtureReply,
} from "./data/fixtures";
import type { ChatMessage, ConnectorId, Conversation } from "./data/types";
import {
  chatReducer,
  initialChatState,
  selectActiveConversation,
  selectVisibleConversations,
} from "./state/chatStore";
import {
  applyTheme,
  readThemeAttributes,
  themeSearch,
  type ThemeAttributes,
} from "./theme/theme";
import {
  deleteConversation,
  fetchAuthStatus,
  fetchConversation,
  fetchConversations,
  streamAnswer,
} from "./api/chatApi";
import { mountOperationalGlassShell } from "./lib/glass-shell";

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
 * The clone talks to the real Chat API when one is reachable: the same
 * `/api/chat/stream` transport, the same conversation routes and the same
 * session cookie the operational product uses. When no API answers, the clone
 * falls back to its local fixtures and says so in the top bar. It never
 * presents a fixture answer as a live one.
 */
export function App() {
  const [themeAttributes, setThemeAttributes] = useState<ThemeAttributes>(() =>
    readThemeAttributes(typeof window === "undefined" ? "" : window.location.search),
  );
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);

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

  /** Loads the server-owned conversation list. */
  const loadApiConversations = useCallback(async () => {
    try {
      const summaries = await fetchConversations();
      const conversations: Conversation[] = summaries.map((summary) => ({
        id: summary.id,
        title: summary.title,
        product: "chat",
        updatedAt: summary.updated_at ?? "",
        messages: [],
      }));
      dispatch({ type: "set-conversations", conversations });
    } catch {
      // The server owns the list. An unavailable history means no list at all,
      // never the fixture list presented as the account's history.
      dispatch({ type: "set-conversations", conversations: [] });
    }
  }, []);

  // One probe decides the mode: the real API when it answers, the local
  // fixtures when it does not. The badge in the top bar says which one it is.
  useEffect(() => {
    const controller = new AbortController();
    fetchAuthStatus(controller.signal)
      .then((status) => {
        // A well-formed "not ready" answer means there is no API to talk to.
        if (!status.ready) {
          dispatch({ type: "set-api-mode", apiMode: "offline" });
          return;
        }
        setAuthenticated(status.authenticated === true);
        dispatch({ type: "set-api-mode", apiMode: "api" });
        return loadApiConversations();
      })
      .catch(() => {
        dispatch({ type: "set-api-mode", apiMode: "offline" });
      });
    return () => controller.abort();
  }, [loadApiConversations]);

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
        fixture: state.apiMode !== "api",
      };
      dispatch({
        type: "send-message",
        conversationId,
        userMessage,
        assistantMessage,
        prompt,
        outbound: [
          ...(activeConversation?.messages ?? []).map((message) => ({
            role: message.role,
            content: message.content,
          })),
          { role: "user" as const, content: prompt },
        ],
      });
      dispatch({ type: "clear-attachment" });
    },
    [activeConversation, state.apiMode],
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
    const sizeLabel =
      file.size >= 1024 * 1024
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

  const handleSelectConversation = useCallback(
    (conversationId: string) => {
      dispatch({ type: "select-conversation", conversationId });
      setMobileOpen(false);
      if (state.apiMode !== "api") return;
      // The server owns the saved turns.
      void fetchConversation(conversationId)
        .then((detail) => {
          const messages: ChatMessage[] = detail.messages.map((message, index) => ({
            id: `api_${detail.id}_${index}`,
            role: message.role,
            content: message.content,
            completedAt: message.completed_at ?? null,
            state: "complete" as const,
            errorMessage: null,
            sourcePrompt: null,
            attempt: 1,
            fixture: false,
          }));
          dispatch({ type: "set-conversation-messages", conversationId, messages });
        })
        .catch(() => {
          /* A failed read keeps the list usable and never invents turns. */
        });
    },
    [state.apiMode],
  );

  const handleDeleteConversation = useCallback(
    (conversationId: string) => {
      if (state.apiMode !== "api") {
        dispatch({ type: "delete-conversation", conversationId });
        return;
      }
      void deleteConversation(conversationId)
        .then(() => loadApiConversations())
        .catch(() => {
          /* The server keeps the record; the list is left as it was. */
        });
    },
    [state.apiMode, loadApiConversations],
  );

  // The answer arrives from the real API, or from the local fixture when no
  // API is reachable. A fixture answer is never labelled as a live one.
  useEffect(() => {
    const pending = state.pendingTurn;
    if (!pending) return;

    if (state.apiMode === "api") {
      const controller = new AbortController();
      void streamAnswer(
        {
          messages: pending.outbound,
          conversationId: state.serverConversationId,
          skill: pending.skill,
          signal: controller.signal,
        },
        {
          onDelta: (delta) => {
            dispatch({
              type: "append-delta",
              conversationId: pending.conversationId,
              messageId: pending.messageId,
              delta,
            });
          },
          onDone: (result) => {
            if (result.conversationId && result.conversationId !== pending.conversationId) {
              dispatch({
                type: "replace-conversation-id",
                from: pending.conversationId,
                to: result.conversationId,
              });
            }
            dispatch({
              type: "resolve-message",
              conversationId: pending.conversationId,
              messageId: pending.messageId,
              content: result.answer,
              completedAt: new Date().toISOString(),
              serverConversationId: result.conversationId,
            });
            void loadApiConversations().catch(() => {
              /* The answer is already on screen; a failed list read is not. */
            });
          },
        },
      )
        .catch((error: unknown) => {
          if (error instanceof Error && error.name === "AbortError") return;
          const message =
            error instanceof Error && error.message
              ? error.message
              : "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.";
          dispatch({
            type: "fail-message",
            conversationId: pending.conversationId,
            messageId: pending.messageId,
            errorMessage: message,
          });
        });
      return () => controller.abort();
    }

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
  }, [state.pendingTurn, state.apiMode, state.serverConversationId, loadApiConversations]);

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
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={handleDeleteConversation}
        onSearchQuery={(query) => dispatch({ type: "set-search-query", query })}
        onToggleCollapse={() => setCollapsed((value) => !value)}
        onCloseMobile={() => setMobileOpen(false)}
        onOpenMode={(mode) => dispatch({ type: "set-mode", mode })}
        authenticated={authenticated}
        apiAvailable={state.apiMode === "api"}
        onOpenLogin={() => setLoginOpen(true)}
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
          apiMode={state.apiMode}
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
          probing={state.apiMode === "probing"}
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
      <LoginDialog
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSignedIn={() => {
          setAuthenticated(true);
          dispatch({ type: "set-api-mode", apiMode: "api" });
          void loadApiConversations();
        }}
      />
    </div>
  );
}
