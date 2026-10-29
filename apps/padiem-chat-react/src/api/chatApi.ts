import { chatTransport } from "../lib/chat-transport";
import type {
  AnswerRequest,
  AnswerResult,
  ApiAuthStatus,
  ApiConversationDetail,
  ApiConversationMessage,
  ApiConversationSummary,
  ApiErrorBody,
} from "./types";

/**
 * #5298 — the real Chat API client.
 *
 * Every request goes to the same-origin `/api` paths, so the operational
 * session cookie and the reviewed same-origin guard keep working when the
 * dev server proxies them. The request bodies and the SSE events are the
 * operational ones; this module only adds the clone's own error handling.
 */

async function readError(response: Response, fallback: string): Promise<Error> {
  const data = (await response.json().catch(() => null)) as ApiErrorBody | null;
  const message =
    data && data.error && typeof data.error.message === "string" ? data.error.message : fallback;
  const error = new Error(message) as Error & { code?: string };
  if (data && data.error && typeof data.error.code === "string") {
    error.code = data.error.code;
  }
  return error;
}

export async function fetchAuthStatus(signal?: AbortSignal): Promise<ApiAuthStatus> {
  const response = await fetch("/api/auth/status", {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw await readError(response, "계정 상태를 확인하지 못했습니다.");
  }
  return (await response.json()) as ApiAuthStatus;
}

/**
 * Signs in with the operational password route.
 *
 * The clone does not have its own authentication. The session is the
 * operational `padiem_session` cookie, and the server owns it. The browser
 * stores the cookie for the dev origin because the dev proxy drops the API
 * host from the cookie's domain attribute.
 */
export async function loginWithPassword(
  identifier: string,
  password: string,
): Promise<ApiAuthStatus> {
  const response = await fetch("/api/auth/password/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ identifier, password }),
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw await readError(response, "로그인 정보를 확인해 주세요.");
  }
  return fetchAuthStatus();
}

export async function fetchConversations(
  signal?: AbortSignal,
): Promise<ApiConversationSummary[]> {
  const response = await fetch("/api/conversations", {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw await readError(response, "저장된 대화를 불러오지 못했습니다.");
  }
  const data = (await response.json()) as { conversations?: ApiConversationSummary[] };
  if (!Array.isArray(data.conversations)) {
    throw new Error("저장된 대화를 불러오지 못했습니다.");
  }
  return data.conversations.filter(
    (conversation) =>
      conversation && typeof conversation.id === "string" && typeof conversation.title === "string",
  );
}

export async function fetchConversation(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ApiConversationDetail> {
  const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw await readError(response, "대화를 불러오지 못했습니다.");
  }
  const data = (await response.json()) as { conversation?: ApiConversationDetail };
  const conversation = data.conversation;
  if (!conversation || !Array.isArray(conversation.messages)) {
    throw new Error("대화를 불러오지 못했습니다.");
  }
  return conversation;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw await readError(response, "대화를 삭제하지 못했습니다.");
  }
  const data = (await response.json().catch(() => null)) as
    | { deleted?: boolean; conversation_id?: string }
    | null;
  if (!data || data.deleted !== true || data.conversation_id !== conversationId) {
    throw new Error("대화를 삭제하지 못했습니다.");
  }
}

/**
 * Streams one answer from the real API.
 *
 * The payload is the operational Chat payload: the outbound messages, the
 * automatic mode and the starter skill. The account tier is deliberately not
 * sent — the server owns the account's tier, and the clone has no tier
 * authority to claim one.
 */
export async function streamAnswer(
  request: AnswerRequest,
  handlers: {
    onDelta: (text: string) => void;
    onDone: (result: AnswerResult) => void;
  },
): Promise<void> {
  const payload: Record<string, unknown> = {
    messages: request.messages,
  };
  if (request.skill) payload.skill = request.skill;
  if (request.conversationId) payload.conversation_id = request.conversationId;

  const response = await chatTransport.requestStreaming(payload, request.signal);

  let answer = "";
  let conversationId = request.conversationId;
  let done = false;

  await chatTransport.readSseEvents(response, async (frame) => {
    if (frame.event !== "delta" && frame.event !== "done" && frame.event !== "error") {
      return false;
    }
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(frame.data) as Record<string, unknown>;
    } catch {
      throw new Error("스트리밍 응답 형식이 올바르지 않습니다.");
    }
    if (frame.event === "delta") {
      if (typeof data.delta !== "string") {
        throw new Error("스트리밍 응답 형식이 올바르지 않습니다.");
      }
      if (!data.delta) return false;
      answer += data.delta;
      handlers.onDelta(data.delta);
      return false;
    }
    if (frame.event === "error") {
      const error = new Error(
        typeof data.message === "string"
          ? data.message
          : "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.",
      ) as Error & { code?: string };
      if (typeof data.code === "string") error.code = data.code;
      throw error;
    }
    // done
    if (typeof data.conversation_id === "string") conversationId = data.conversation_id;
    done = true;
    handlers.onDone({ answer, conversationId });
    return true;
  });

  if (!done) {
    throw new Error("AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.");
  }
}

export function toApiMessages(
  messages: { role: "user" | "assistant"; content: string }[],
): ApiConversationMessage[] {
  return messages.map((message) => ({ role: message.role, content: message.content }));
}
