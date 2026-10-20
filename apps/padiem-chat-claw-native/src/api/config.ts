/**
 * PADIEM API endpoint contract.
 *
 * Every path here is an EXISTING server route of the deployed PADIEM platform
 * (B62 Chat / B54 Claw / Control Plane). The native app never invents a route
 * and never re-implements an auth, tier or model rule: it consumes the same
 * contracts the Web client consumes.
 */

export const DEFAULT_API_BASE_URL = 'https://chat.padiem.net';

export const ENDPOINTS = {
  health: '/health',
  authStatus: '/api/auth/status',
  authLogout: '/api/auth/logout',
  passwordLogin: '/api/auth/password/login',

  /** Android sign-in return contract (external-browser Google handoff). */
  androidHandoff: '/auth/android/handoff',
  androidHandoffById: (id: string) => `/auth/android/handoff/${encodeURIComponent(id)}`,
  androidHandoffClaim: (id: string) => `/auth/android/handoff/${encodeURIComponent(id)}/claim`,

  modelSelection: '/api/account/model-selection',
  conversations: '/api/conversations',
  conversation: (id: string) => `/api/conversations/${encodeURIComponent(id)}`,
  conversationSearch: '/api/conversations/search',

  chat: '/api/chat',
  chatStream: '/api/chat/stream',

  clawGeneral: '/api/claw/general',
  clawGeneralCapabilities: '/api/claw/general/capabilities',
  clawLocalAccess: '/api/claw/local-access',
  clawDeviceDirectory: '/api/claw/local-access/devices',
  clawDeviceSelect: '/api/claw/local-access/devices/select',
  clawLocalConnect: '/api/claw/local-access/connect',
  clawRuns: '/api/claw/runs',
  clawPendingResult: (runId: string) => `/api/claw/runs/${encodeURIComponent(runId)}/pending-result`,
  clawApprovalDecision: '/api/claw/approvals/decision',
  clawVerifiedModelChoices: '/api/claw/verified-model-choices',

  voiceIdentity: '/api/voice/identity',
  voiceTranscribe: '/api/voice/transcribe',
  clawVoiceIdentity: '/api/claw/voice/identity',
  clawVoiceTranscribe: '/api/claw/voice/transcribe',
} as const;

/** Header carrying the one-time claim secret of an Android sign-in handoff. */
export const ANDROID_HANDOFF_SECRET_HEADER = 'X-Padiem-Handoff-Secret';

/** Live P01 event stream marker used by the Claw general composer. */
export const CLAW_LIVE_REQUEST_HEADER = 'X-Padiem-Claw-Live';
export const CLAW_LIVE_REQUEST_MARKER = 'p01-events-v1';

/** The session cookie the existing server issues. The native app stores its
 *  value and replays it as a `Cookie` header — same credential, same server
 *  authority, no second identity system. */
export const SESSION_COOKIE_NAME = 'padiem_session';
