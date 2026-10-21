/**
 * #5298 — typed access to the operational chat transport.
 *
 * `apps/padiem-chat/static/chat-transport.js` is the single source for the
 * Chat request contract: the `/api/chat/stream` and `/api/chat` endpoints, the
 * orchestration readiness check, and the SSE frame reader. The clone consumes
 * that module instead of restating the wire format, so the two builds cannot
 * disagree about the transport.
 */

import "../../../../apps/padiem-chat/static/chat-transport.js";

export interface TransportError extends Error {
  code?: string;
}

export interface SseFrame {
  event: string;
  data: string;
}

export interface ChatTransportApi {
  readonly VERSION?: string;
  createCalendarTurnId(): string | null;
  errorFor(data: unknown, fallback: string): TransportError;
  parseSseFrame(frame: string): SseFrame | null;
  readSseEvents(
    response: Response,
    onEvent: (frame: SseFrame) => boolean | Promise<boolean>,
  ): Promise<void>;
  requestCompleted(payload: unknown, signal?: AbortSignal): Promise<Record<string, unknown>>;
  requestStreaming(payload: unknown, signal?: AbortSignal): Promise<Response>;
  orchestrationReady(signal?: AbortSignal): Promise<boolean>;
  resumeOrchestration(intent: unknown, signal?: AbortSignal): Promise<Record<string, unknown>>;
  cancelOrchestration(intent: unknown, signal?: AbortSignal): Promise<Record<string, unknown>>;
  setOrchestrationPauseHandler(handler: ((...args: unknown[]) => void) | null): void;
}

const runtime = globalThis as typeof globalThis & {
  PadiemChatTransport?: ChatTransportApi;
};

const transport = runtime.PadiemChatTransport;

if (!transport) {
  throw new Error(
    "apps/padiem-chat/static/chat-transport.js did not publish PadiemChatTransport",
  );
}

export const chatTransport: ChatTransportApi = transport;
