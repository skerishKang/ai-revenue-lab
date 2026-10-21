/**
 * #5298 — the shapes the operational Chat API returns.
 *
 * These mirror `apps/padiem-chat/app/conversation_routes.py` and
 * `app/auth_routes.py`. The clone reads the same contract; it never invents
 * a field the server does not send.
 */

export interface ApiUser {
  id?: string;
  username?: string;
  email?: string;
  name?: string;
}

export interface ApiAuthStatus {
  ready: boolean;
  authenticated: boolean;
  history_ready: boolean;
  user: ApiUser | null;
  model_requires_session: boolean;
  session_state: string;
  methods: {
    google?: boolean;
    password?: boolean;
  };
  project_files_ready?: boolean;
}

export interface ApiConversationSummary {
  id: string;
  title: string;
  updated_at?: string;
  project_id?: string | null;
}

export interface ApiConversationMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  completed_at?: string;
}

export interface ApiConversationDetail {
  id: string;
  title: string;
  project_id?: string | null;
  messages: ApiConversationMessage[];
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
  };
}

export interface OutboundMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AnswerRequest {
  messages: OutboundMessage[];
  /** Continue an existing conversation. `null` starts a new one. */
  conversationId: string | null;
  skill?: string;
  signal: AbortSignal;
}

export interface AnswerResult {
  answer: string;
  conversationId: string | null;
}
