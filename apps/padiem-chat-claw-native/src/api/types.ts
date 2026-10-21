/** Shared wire types for the existing PADIEM server contracts. */

export type Tier = 'free' | 'plus' | 'pro' | 'max' | 'admin';

export const TIER_ORDER: readonly Tier[] = ['free', 'plus', 'pro', 'max'];

export const TIER_LABELS: Record<Tier, string> = {
  free: 'Padiem Free',
  plus: 'Padiem Plus',
  pro: 'Padiem Pro',
  max: 'Padiem Max',
  admin: 'Padiem Admin',
};

export type SessionState = 'guest' | 'signed_in' | 'expired' | 'unavailable';

export interface PublicUser {
  id: string;
  display_name?: string | null;
  email?: string | null;
  username?: string | null;
  [key: string]: unknown;
}

export interface AuthStatus {
  ready: boolean;
  authenticated: boolean;
  history_ready: boolean;
  user: PublicUser | null;
  model_requires_session?: boolean;
  member_grade?: Tier | string;
  session_state?: SessionState;
}

export interface ModelSelection {
  ok: boolean;
  selection: { tier: Tier } | null;
  stored_tier: Tier | null;
  restorable_tier: Tier | null;
  allowed_tiers: Tier[];
  admin_available: boolean | null;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ConversationSummary {
  id: string;
  title?: string | null;
  preview?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  project_id?: string | null;
  [key: string]: unknown;
}

export interface ConversationDetail extends ConversationSummary {
  messages?: ChatMessage[];
}

export interface ConversationsResponse {
  conversations: ConversationSummary[];
}

export interface ConversationDetailResponse {
  conversation: ConversationDetail;
}

export interface AndroidHandoffCreated {
  handoff_id: string;
  claim_secret: string;
  user_code: string;
  authorization_url: string;
  expires_in: number;
}

export interface AndroidHandoffStatus {
  status:
    | 'awaiting_login'
    | 'awaiting_confirmation'
    | 'ready'
    | 'claimed'
    | 'cancelled'
    | 'expired';
  expires_in: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; detail?: string };
}

export interface VoiceIdentity {
  ok?: boolean;
  available?: boolean;
  reason?: string;
  [key: string]: unknown;
}

export interface VoiceTranscribeResult {
  text?: string;
  utterance_id?: string;
  provider?: string;
  [key: string]: unknown;
}

export interface ClawDevice {
  device_id: string;
  label?: string | null;
  state?: string;
  connected?: boolean;
  [key: string]: unknown;
}

export interface ClawLocalAccess {
  ok?: boolean;
  available?: boolean;
  reason?: string | null;
  [key: string]: unknown;
}
