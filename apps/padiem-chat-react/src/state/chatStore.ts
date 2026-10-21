import type {
  ChatMessage,
  ConnectorCard,
  ConnectorState,
  Conversation,
  ModelChoice,
  PendingAttachment,
  ProductMode,
} from "../data/types";

/**
 * #5298 — first-screen state.
 *
 * The reducer is intentionally free of any transport. A later PR replaces the
 * fixture source with the existing B62/B14 conversation API by dispatching the
 * same actions; the component tree does not change.
 */

export interface PendingTurn {
  conversationId: string;
  messageId: string;
  prompt: string;
  attempt: number;
  /** The skill the starter carried, if any. The API payload keeps the same field. */
  skill?: string;
  /**
   * The exact outbound messages of this turn. They are fixed when the turn
   * starts, so a streaming answer is never restarted by a state change.
   */
  outbound: { role: "user" | "assistant"; content: string }[];
}

export type ApiMode = "probing" | "api" | "offline";

export interface ChatState {
  conversations: Conversation[];
  activeConversationId: string | null;
  /** The server-side conversation id of the active thread, once the API issued one. */
  serverConversationId: string | null;
  mode: ProductMode;
  apiMode: ApiMode;
  modelId: string;
  modelChoices: ModelChoice[];
  connectors: ConnectorCard[];
  pendingAttachment: PendingAttachment | null;
  searchQuery: string;
  pendingTurn: PendingTurn | null;
}

export type ChatAction =
  | { type: "select-conversation"; conversationId: string }
  | { type: "create-conversation"; conversationId: string; title: string }
  | { type: "delete-conversation"; conversationId: string }
  | { type: "set-conversations"; conversations: Conversation[] }
  | { type: "replace-conversation-id"; from: string; to: string }
  | { type: "set-conversation-messages"; conversationId: string; messages: ChatMessage[] }
  | { type: "set-api-mode"; apiMode: ApiMode }
  | { type: "set-mode"; mode: ProductMode }
  | { type: "set-model"; modelId: string }
  | { type: "set-search-query"; query: string }
  | { type: "attach-file"; attachment: PendingAttachment }
  | { type: "clear-attachment" }
  | {
      type: "send-message";
      conversationId: string;
      userMessage: ChatMessage;
      assistantMessage: ChatMessage;
      prompt: string;
      skill?: string;
      outbound: { role: "user" | "assistant"; content: string }[];
    }
  | { type: "append-delta"; conversationId: string; messageId: string; delta: string }
  | { type: "retry-message"; conversationId: string; messageId: string }
  | {
      type: "resolve-message";
      conversationId: string;
      messageId: string;
      content: string;
      completedAt: string;
      serverConversationId?: string | null;
    }
  | { type: "fail-message"; conversationId: string; messageId: string; errorMessage: string }
  | { type: "set-connector-state"; connectorId: string; state: ConnectorState };

export function initialChatState(
  conversations: Conversation[],
  modelChoices: ModelChoice[],
  connectors: ConnectorCard[],
): ChatState {
  return {
    conversations,
    activeConversationId: conversations[0]?.id ?? null,
    serverConversationId: null,
    mode: "chat",
    apiMode: "probing",
    modelId: modelChoices[0]?.id ?? "",
    modelChoices,
    connectors,
    pendingAttachment: null,
    searchQuery: "",
    pendingTurn: null,
  };
}

function replaceConversation(
  conversations: Conversation[],
  conversationId: string,
  update: (conversation: Conversation) => Conversation,
): Conversation[] {
  return conversations.map((conversation) =>
    conversation.id === conversationId ? update(conversation) : conversation,
  );
}

function updateMessage(
  conversation: Conversation,
  messageId: string,
  update: (message: ChatMessage) => ChatMessage,
): Conversation {
  return {
    ...conversation,
    updatedAt: new Date().toISOString(),
    messages: conversation.messages.map((message) =>
      message.id === messageId ? update(message) : message,
    ),
  };
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "select-conversation": {
      const target = state.conversations.find(
        (conversation) => conversation.id === action.conversationId,
      );
      if (!target) return state;
      return {
        ...state,
        activeConversationId: target.id,
        mode: target.product,
        serverConversationId: null,
        pendingTurn: null,
      };
    }
    case "create-conversation": {
      const conversation: Conversation = {
        id: action.conversationId,
        title: action.title,
        product: state.mode,
        updatedAt: new Date().toISOString(),
        messages: [],
      };
      return {
        ...state,
        conversations: [conversation, ...state.conversations],
        activeConversationId: conversation.id,
        mode: conversation.product,
        serverConversationId: null,
        pendingTurn: null,
      };
    }
    case "delete-conversation": {
      const conversations = state.conversations.filter(
        (conversation) => conversation.id !== action.conversationId,
      );
      const activeConversationId =
        state.activeConversationId === action.conversationId
          ? (conversations[0]?.id ?? null)
          : state.activeConversationId;
      return {
        ...state,
        conversations,
        activeConversationId,
        serverConversationId:
          state.activeConversationId === action.conversationId ? null : state.serverConversationId,
      };
    }
    case "set-conversations": {
      // The server owns the list. A conversation that is already open keeps the
      // turns that are rendered for it, so a reload never blanks the panel.
      const previous = new Map(state.conversations.map((c) => [c.id, c]));
      const conversations = action.conversations.map((conversation) => ({
        ...conversation,
        messages: previous.get(conversation.id)?.messages ?? conversation.messages,
      }));
      const activeConversationId =
        conversations.find((conversation) => conversation.id === state.activeConversationId)?.id ??
        conversations[0]?.id ??
        null;
      return {
        ...state,
        conversations,
        activeConversationId,
        serverConversationId:
          state.activeConversationId === activeConversationId ? state.serverConversationId : null,
      };
    }
    case "replace-conversation-id": {
      // The server issues the conversation id when the first answer lands. The
      // open thread keeps its turns under the server's id.
      if (action.from === action.to) return state;
      const conversations = state.conversations.map((conversation) =>
        conversation.id === action.from ? { ...conversation, id: action.to } : conversation,
      );
      return {
        ...state,
        conversations,
        activeConversationId:
          state.activeConversationId === action.from ? action.to : state.activeConversationId,
      };
    }
    case "set-conversation-messages": {
      return {
        ...state,
        conversations: replaceConversation(
          state.conversations,
          action.conversationId,
          (conversation) => ({ ...conversation, messages: action.messages }),
        ),
      };
    }
    case "set-api-mode":
      return { ...state, apiMode: action.apiMode };
    case "set-mode":
      return { ...state, mode: action.mode };
    case "set-model":
      return { ...state, modelId: action.modelId };
    case "set-search-query":
      return { ...state, searchQuery: action.query };
    case "attach-file":
      return { ...state, pendingAttachment: action.attachment };
    case "clear-attachment":
      return { ...state, pendingAttachment: null };
    case "send-message": {
      const conversations = replaceConversation(
        state.conversations,
        action.conversationId,
        (conversation) => ({
          ...conversation,
          updatedAt: new Date().toISOString(),
          messages: [...conversation.messages, action.userMessage, action.assistantMessage],
        }),
      );
      return {
        ...state,
        conversations,
        pendingTurn: {
          conversationId: action.conversationId,
          messageId: action.assistantMessage.id,
          prompt: action.prompt,
          attempt: action.assistantMessage.attempt,
          skill: action.skill,
          outbound: action.outbound,
        },
      };
    }
    case "append-delta": {
      return {
        ...state,
        conversations: replaceConversation(
          state.conversations,
          action.conversationId,
          (conversation) =>
            updateMessage(conversation, action.messageId, (message) => ({
              ...message,
              content: message.content + action.delta,
            })),
        ),
      };
    }
    case "retry-message": {
      const conversation = state.conversations.find(
        (item) => item.id === action.conversationId,
      );
      const message = conversation?.messages.find((item) => item.id === action.messageId);
      if (!conversation || !message) return state;
      return {
        ...state,
        conversations: replaceConversation(
          state.conversations,
          action.conversationId,
          (current) =>
            updateMessage(current, action.messageId, (item) => ({
              ...item,
              state: "streaming",
              errorMessage: null,
              content: "",
              attempt: item.attempt + 1,
            })),
        ),
        pendingTurn: {
          conversationId: action.conversationId,
          messageId: action.messageId,
          prompt: message.sourcePrompt ?? "",
          attempt: message.attempt + 1,
          skill: undefined,
          // The retry replays the same turns, without the failed answer.
          outbound: (conversation?.messages ?? [])
            .filter((item) => item.id !== action.messageId)
            .map((item) => ({ role: item.role, content: item.content })),
        },
      };
    }
    case "resolve-message":
      return {
        ...state,
        conversations: replaceConversation(
          state.conversations,
          action.conversationId,
          (conversation) =>
            updateMessage(conversation, action.messageId, (message) => ({
              ...message,
              content: action.content,
              state: "complete",
              completedAt: action.completedAt,
              errorMessage: null,
            })),
        ),
        serverConversationId:
          action.serverConversationId === undefined
            ? state.serverConversationId
            : action.serverConversationId,
        pendingTurn: null,
      };
    case "fail-message":
      return {
        ...state,
        conversations: replaceConversation(
          state.conversations,
          action.conversationId,
          (conversation) =>
            updateMessage(conversation, action.messageId, (message) => ({
              ...message,
              state: "error",
              errorMessage: action.errorMessage,
            })),
        ),
        pendingTurn: null,
      };
    case "set-connector-state":
      return {
        ...state,
        connectors: state.connectors.map((connector) =>
          connector.id === action.connectorId
            ? { ...connector, state: action.state }
            : connector,
        ),
      };
    default:
      return state;
  }
}

export function selectActiveConversation(state: ChatState): Conversation | null {
  if (!state.activeConversationId) return null;
  return (
    state.conversations.find(
      (conversation) => conversation.id === state.activeConversationId,
    ) ?? null
  );
}

export function selectVisibleConversations(state: ChatState): Conversation[] {
  const query = state.searchQuery.trim().toLowerCase();
  if (!query) return state.conversations;
  return state.conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(query),
  );
}
