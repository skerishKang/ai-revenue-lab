import {CLAW_LIVE_REQUEST_HEADER, CLAW_LIVE_REQUEST_MARKER, ENDPOINTS} from './config';
import {apiRequest} from './http';
import {openSseRequest, SseEvent} from './sse';
import {
  AndroidHandoffCreated,
  AuthStatus,
  ChatMessage,
  ConversationDetail,
  ConversationDetailResponse,
  ConversationsResponse,
  ModelSelection,
  Tier,
  VoiceIdentity,
  VoiceTranscribeResult,
} from './types';
import {currentBaseUrl} from './baseUrl';
import {sessionCookieHeader} from '../auth/session';

export interface ChatRequest {
  messages: ChatMessage[];
  tier: Tier;
  conversationId?: string | null;
  projectId?: string | null;
  skill?: string;
  deviceId?: string | null;
  timezone?: string | null;
  calendarTurnId?: string | null;
  attachments?: unknown[];
}

export interface ChatStreamHandlers {
  onDelta: (delta: string) => void;
  onDone: (payload: {conversation_id?: string; project_id?: string}) => void;
  onError: (error: Error) => void;
  onClose?: () => void;
}

function buildChatBody(request: ChatRequest): Record<string, unknown> {
  const body: Record<string, unknown> = {
    messages: request.messages.map(item => ({
      role: item.role,
      content: item.content,
    })),
    mode: 'auto',
    tier: request.tier,
    skill: request.skill ?? 'auto',
  };
  if (request.conversationId) {
    body.conversation_id = request.conversationId;
  }
  if (request.projectId) {
    body.project_id = request.projectId;
  }
  if (request.deviceId) {
    body.device_id = request.deviceId;
  }
  if (request.timezone) {
    body.timezone = request.timezone;
  }
  if (request.calendarTurnId) {
    body.calendar_turn_id = request.calendarTurnId;
  }
  if (request.attachments && request.attachments.length > 0) {
    body.attachments = request.attachments;
  }
  return body;
}

async function streamRequest(
  url: string,
  body: Record<string, unknown>,
  handlers: ChatStreamHandlers,
  extraHeaders: Record<string, string> = {},
): Promise<() => void> {
  const cookie = await sessionCookieHeader();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...extraHeaders,
  };
  if (cookie) {
    headers.Cookie = cookie;
  }

  const controller = new AbortController();

  return openSseRequest({
    url,
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: controller.signal,
    onEvent: (event: SseEvent) => {
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(event.data) as Record<string, unknown>;
      } catch {
        return;
      }
      if (event.event === 'delta') {
        const delta = payload.delta;
        if (typeof delta === 'string') {
          handlers.onDelta(delta);
        }
        return;
      }
      if (event.event === 'done') {
        handlers.onDone({
          conversation_id:
            typeof payload.conversation_id === 'string' ? payload.conversation_id : undefined,
          project_id: typeof payload.project_id === 'string' ? payload.project_id : undefined,
        });
        return;
      }
      if (event.event === 'error') {
        const error = payload.error as {code?: string; message?: string} | undefined;
        handlers.onError(
          new Error(error?.message ?? '스트리밍 답변을 계속하지 못했습니다.'),
        );
      }
    },
    onError: (error: Error) => {
      handlers.onError(error);
    },
    onClose: () => {
      handlers.onClose?.();
    },
  });
}

export const padiemApi = {
  authStatus: (): Promise<AuthStatus> => apiRequest<AuthStatus>(ENDPOINTS.authStatus),

  createAndroidHandoff: (): Promise<AndroidHandoffCreated> =>
    apiRequest<AndroidHandoffCreated>(ENDPOINTS.androidHandoff, {
      method: 'POST',
      body: {},
      anonymous: true,
    }),

  modelSelection: (): Promise<ModelSelection> =>
    apiRequest<ModelSelection>(ENDPOINTS.modelSelection),

  saveModelSelection: (tier: Tier): Promise<ModelSelection> =>
    apiRequest<ModelSelection>(ENDPOINTS.modelSelection, {
      method: 'PUT',
      body: {tier},
    }),

  conversations: (): Promise<ConversationsResponse> =>
    apiRequest<ConversationsResponse>(ENDPOINTS.conversations),

  conversation: (id: string): Promise<ConversationDetailResponse> =>
    apiRequest<ConversationDetailResponse>(ENDPOINTS.conversation(id)),

  deleteConversation: (id: string): Promise<{deleted: boolean}> =>
    apiRequest<{deleted: boolean}>(ENDPOINTS.conversation(id), {method: 'DELETE'}),

  searchConversations: (query: string): Promise<ConversationsResponse> =>
    apiRequest<ConversationsResponse>(
      `${ENDPOINTS.conversationSearch}?q=${encodeURIComponent(query)}`,
    ),

  /** Stream one Chat answer over the existing `text/event-stream` contract. */
  streamChat: (request: ChatRequest, handlers: ChatStreamHandlers): Promise<() => void> =>
    streamRequest(`${currentBaseUrl()}${ENDPOINTS.chatStream}`, buildChatBody(request), handlers),

  /** Stream one Claw answer over the canonical P01 Engine lane. */
  streamClawGeneral: (
    request: ChatRequest,
    handlers: ChatStreamHandlers,
  ): Promise<() => void> =>
    streamRequest(
      `${currentBaseUrl()}${ENDPOINTS.clawGeneral}`,
      buildChatBody(request),
      handlers,
      {[CLAW_LIVE_REQUEST_HEADER]: CLAW_LIVE_REQUEST_MARKER},
    ),

  clawCapabilities: (): Promise<{live_events_available?: boolean}> =>
    apiRequest<{live_events_available?: boolean}>(ENDPOINTS.clawGeneralCapabilities),

  clawLocalAccess: (conversationId?: string | null): Promise<Record<string, unknown>> =>
    apiRequest<Record<string, unknown>>(
      conversationId
        ? `${ENDPOINTS.clawLocalAccess}?conversationId=${encodeURIComponent(conversationId)}`
        : ENDPOINTS.clawLocalAccess,
    ),

  clawDevices: (): Promise<Record<string, unknown>> =>
    apiRequest<Record<string, unknown>>(ENDPOINTS.clawDeviceDirectory),

  clawSelectDevice: (deviceId: string): Promise<Record<string, unknown>> =>
    apiRequest<Record<string, unknown>>(ENDPOINTS.clawDeviceSelect, {
      method: 'POST',
      body: {device_id: deviceId},
    }),

  clawConnect: (): Promise<Record<string, unknown>> =>
    apiRequest<Record<string, unknown>>(ENDPOINTS.clawLocalConnect, {method: 'POST', body: {}}),

  clawRuns: (): Promise<Record<string, unknown>> =>
    apiRequest<Record<string, unknown>>(ENDPOINTS.clawRuns),

  clawPendingResult: (runId: string): Promise<Record<string, unknown>> =>
    apiRequest<Record<string, unknown>>(ENDPOINTS.clawPendingResult(runId)),

  clawApprovalDecision: (
    runId: string,
    decision: 'approve' | 'reject',
  ): Promise<Record<string, unknown>> =>
    apiRequest<Record<string, unknown>>(ENDPOINTS.clawApprovalDecision, {
      method: 'POST',
      body: {run_id: runId, decision},
    }),

  voiceIdentity: (claw = false): Promise<VoiceIdentity> =>
    apiRequest<VoiceIdentity>(claw ? ENDPOINTS.clawVoiceIdentity : ENDPOINTS.voiceIdentity),

  voiceTranscribe: (
    audioBase64: string,
    mimeType: string,
    utteranceId: string,
    claw = false,
  ): Promise<VoiceTranscribeResult> =>
    apiRequest<VoiceTranscribeResult>(
      claw ? ENDPOINTS.clawVoiceTranscribe : ENDPOINTS.voiceTranscribe,
      {
        method: 'POST',
        body: {
          audio_base64: audioBase64,
          mime_type: mimeType,
          utterance_id: utteranceId,
        },
      },
    ),
};

export type PadiemApi = typeof padiemApi;
export type {ConversationDetail};
