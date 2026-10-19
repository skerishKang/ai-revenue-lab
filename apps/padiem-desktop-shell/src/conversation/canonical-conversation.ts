/**
 * #3436 B2b — Desktop-side consumer of the canonical Padiem conversation
 * authority (apps/padiem-chat HistoryStore, exposed as /api/conversations).
 *
 * Authority boundary:
 *
 *   SECOND_CONVERSATION_AUTHORITY=0        Desktop mints no conversation id and
 *                                          stores no conversation state. Every
 *                                          id and every message on this surface
 *                                          came from the canonical server in the
 *                                          current call; nothing is persisted.
 *   DESKTOP_CONVERSATION_ID_MINTING=0      The id grammar accepted here is the
 *                                          server's own `chat_` + 32 lowercase
 *                                          hex (`history.validate_conversation_id`).
 *                                          It is validated so a malformed or
 *                                          caller-shaped id fails closed before
 *                                          any request leaves the process, never
 *                                          so the Desktop can create one.
 *   DESKTOP_LOCAL_CONVERSATION_DATABASE=0  No localStorage, no file, no cache.
 *   DESKTOP_ONLY_MESSAGE_HISTORY=0         The transcript projection is a copy
 *                                          of the canonical response, bounded
 *                                          and fail-closed on any malformed
 *                                          payload.
 *
 * The transport is injected: the main process supplies an authenticated
 * canonical fetch port when the Desktop holds a canonical session credential,
 * and an UnconfiguredCanonicalConversationPort otherwise. An unconfigured port
 * is the honest fail-closed answer — the same presentation as "canonical
 * conversation unavailable", never a temporary local conversation.
 */

import type {
  CanonicalConversationDetail,
  CanonicalConversationListResponse,
  CanonicalConversationListItem,
  CanonicalConversationMessage,
  CanonicalConversationReadResponse,
} from '../contract/ipc.js';

/** Mirrors `history.validate_conversation_id`: `chat_` + 32 lowercase hex. */
export const CANONICAL_CONVERSATION_ID_PATTERN = /^chat_[0-9a-f]{32}$/;

/** Mirrors `history.MAX_RECENT_CONVERSATIONS` behaviour for a bounded list. */
export const MAX_CANONICAL_CONVERSATIONS = 50;
export const MAX_CANONICAL_MESSAGES = 500;
const MAX_TITLE_LENGTH = 300;
const MAX_MESSAGE_LENGTH = 100_000;
const MAX_TIMESTAMP_LENGTH = 64;

export interface CanonicalConversationPort {
  readonly configured: boolean;
  listConversations(): Promise<unknown>;
  readConversation(conversationId: string): Promise<unknown>;
}

/**
 * Fail-closed default: no canonical credential is available to the Desktop yet.
 *
 * Reading the canonical conversation list needs the signed-in Padiem session
 * credential, which the Desktop does not hold in this slice. Until that channel
 * is established (a CENTRAL decision), every call reports the conversation
 * surface as unavailable instead of inventing one.
 */
export class UnconfiguredCanonicalConversationPort implements CanonicalConversationPort {
  readonly configured = false;

  async listConversations(): Promise<unknown> {
    throw new Error('canonical conversation port is not configured');
  }

  async readConversation(_conversationId: string): Promise<unknown> {
    throw new Error('canonical conversation port is not configured');
  }
}

export type ConversationListErrorCode =
  | 'canonical_conversation_unavailable'
  | 'invalid_conversation_payload';

export type ConversationReadErrorCode =
  | 'canonical_conversation_unavailable'
  | 'invalid_conversation_id'
  | 'conversation_not_found'
  | 'invalid_conversation_payload';

export class CanonicalConversationController {
  readonly #port: CanonicalConversationPort;

  constructor(port: CanonicalConversationPort = new UnconfiguredCanonicalConversationPort()) {
    this.#port = port;
  }

  get configured(): boolean {
    return this.#port.configured;
  }

  async listConversations(): Promise<CanonicalConversationListResponse> {
    if (!this.#port.configured) {
      return Object.freeze({
        ok: false,
        configured: false,
        conversations: Object.freeze([]),
        errorCode: 'canonical_conversation_unavailable' as const,
      });
    }
    let payload: unknown;
    try {
      payload = await this.#port.listConversations();
    } catch {
      return Object.freeze({
        ok: false,
        configured: true,
        conversations: Object.freeze([]),
        errorCode: 'canonical_conversation_unavailable' as const,
      });
    }
    const conversations = parseConversationList(payload);
    if (conversations === null) {
      return Object.freeze({
        ok: false,
        configured: true,
        conversations: Object.freeze([]),
        errorCode: 'invalid_conversation_payload' as const,
      });
    }
    return Object.freeze({
      ok: true,
      configured: true,
      conversations: Object.freeze(conversations),
      errorCode: null,
    });
  }

  /**
   * Reads one canonical conversation. The caller never supplies an absolute
   * path or an arbitrary identifier surface: only an id matching the canonical
   * grammar is ever forwarded, and only for an owner-scoped server lookup whose
   * response is validated here before projection.
   */
  async readConversation(request: unknown): Promise<CanonicalConversationReadResponse> {
    const conversationId = extractConversationId(request);
    if (conversationId === null) {
      return Object.freeze({
        ok: false,
        conversation: null,
        errorCode: 'invalid_conversation_id' as const,
      });
    }
    if (!this.#port.configured) {
      return Object.freeze({
        ok: false,
        conversation: null,
        errorCode: 'canonical_conversation_unavailable' as const,
      });
    }
    let payload: unknown;
    try {
      payload = await this.#port.readConversation(conversationId);
    } catch {
      return Object.freeze({
        ok: false,
        conversation: null,
        errorCode: 'canonical_conversation_unavailable' as const,
      });
    }
    if (payload === null || payload === undefined) {
      return Object.freeze({
        ok: false,
        conversation: null,
        errorCode: 'conversation_not_found' as const,
      });
    }
    const conversation = parseConversationDetail(payload);
    if (conversation === null) {
      return Object.freeze({
        ok: false,
        conversation: null,
        errorCode: 'invalid_conversation_payload' as const,
      });
    }
    if (conversation.id !== conversationId) {
      return Object.freeze({
        ok: false,
        conversation: null,
        errorCode: 'invalid_conversation_payload' as const,
      });
    }
    return Object.freeze({
      ok: true,
      conversation: Object.freeze(conversation),
      errorCode: null,
    });
  }
}

/**
 * Accepts only a plain request whose `relativePath`-style shape matches the
 * closed contract: `{ conversationId }`. Extra fields are ignored, never
 * forwarded, so a renderer-shaped caller cannot widen the request.
 */
function extractConversationId(request: unknown): string | null {
  if (request === undefined || request === null) return null;
  if (typeof request !== 'object' || Array.isArray(request)) return null;
  const value = (request as { conversationId?: unknown }).conversationId;
  if (typeof value !== 'string' || !CANONICAL_CONVERSATION_ID_PATTERN.test(value)) {
    return null;
  }
  return value;
}

function parseConversationList(payload: unknown): readonly CanonicalConversationListItem[] | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const raw = (payload as { conversations?: unknown }).conversations;
  if (!Array.isArray(raw)) return null;
  const rows: CanonicalConversationListItem[] = [];
  for (const item of raw.slice(0, MAX_CANONICAL_CONVERSATIONS)) {
    const parsed = parseConversationListItem(item);
    if (parsed === null) return null;
    rows.push(parsed);
  }
  return rows;
}

function parseConversationListItem(payload: unknown): CanonicalConversationListItem | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const source = payload as Record<string, unknown>;
  const id = typeof source.id === 'string' && CANONICAL_CONVERSATION_ID_PATTERN.test(source.id)
    ? source.id
    : null;
  if (id === null) return null;
  const title = boundedText(source.title, MAX_TITLE_LENGTH);
  const createdAt = boundedText(source.created_at ?? source.createdAt, MAX_TIMESTAMP_LENGTH);
  const updatedAt = boundedText(source.updated_at ?? source.updatedAt, MAX_TIMESTAMP_LENGTH);
  return Object.freeze({
    id,
    title: title ?? '',
    createdAt: createdAt ?? '',
    updatedAt: updatedAt ?? '',
  });
}

function parseConversationDetail(payload: unknown): CanonicalConversationDetail | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const source = (payload as { conversation?: unknown }).conversation ?? payload;
  if (typeof source !== 'object' || source === null || Array.isArray(source)) return null;
  const record = source as Record<string, unknown>;
  const id =
    typeof record.id === 'string' && CANONICAL_CONVERSATION_ID_PATTERN.test(record.id)
      ? record.id
      : null;
  if (id === null) return null;
  const title = boundedText(record.title, MAX_TITLE_LENGTH);
  const createdAt = boundedText(record.created_at ?? record.createdAt, MAX_TIMESTAMP_LENGTH);
  const updatedAt = boundedText(record.updated_at ?? record.updatedAt, MAX_TIMESTAMP_LENGTH);
  const rawMessages = record.messages;
  if (!Array.isArray(rawMessages)) return null;
  const messages: CanonicalConversationMessage[] = [];
  for (const item of rawMessages.slice(0, MAX_CANONICAL_MESSAGES)) {
    const parsed = parseMessage(item);
    if (parsed === null) return null;
    messages.push(parsed);
  }
  return Object.freeze({
    id,
    title: title ?? '',
    createdAt: createdAt ?? '',
    updatedAt: updatedAt ?? '',
    messages: Object.freeze(messages),
  });
}

function parseMessage(payload: unknown): CanonicalConversationMessage | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  const role = record.role;
  if (role !== 'user' && role !== 'assistant') return null;
  const content = boundedText(record.content, MAX_MESSAGE_LENGTH);
  if (content === null) return null;
  return Object.freeze({ role, content });
}

function boundedText(value: unknown, maximum: number): string | null {
  if (typeof value !== 'string') return null;
  return value.length > maximum ? value.slice(0, maximum) : value;
}
