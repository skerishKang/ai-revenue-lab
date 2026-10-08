/* B66 voice lane (#3404) — Gemini Live grant minting.
   This module lives apart from _worker.js on purpose: the Pages contract forbids
   credential vocabulary inside the bridge worker (tests/pages-live-intake.test.mjs),
   and that invariant is worth more than saving a file. Everything that has to know
   the long-lived key is here, and the key is only ever placed in one request header. */

const GEMINI_AUTH_TOKEN_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/auth_tokens";
const GEMINI_LIVE_WS_BASE = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent";
const MAX_VOICE_TOKEN_BODY_BYTES = 512;
const STT_MODEL_NAME = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/;
const STT_LANGUAGE_TAG = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
const VOICE_TOKEN_SESSION_SECONDS = 1800;
const VOICE_TOKEN_NEW_SESSION_SECONDS = 60;

async function readStoredValue(env, bindingName) {
  const binding = env && env[bindingName];
  if (!binding) return null;
  /* A Secrets Store binding is resolved asynchronously; a plain string is what the
     same name looks like in local development. Reading either shape as a string
     would silently send "[object Object]" upstream instead of failing closed. */
  if (typeof binding.get === "function") {
    try {
      const value = await binding.get();
      return typeof value === "string" && value ? value : null;
    } catch (_) {
      return null;
    }
  }
  return typeof binding === "string" && binding ? binding : null;
}

function configuration(env) {
  const model = String((env && env.B66_STT_MODEL) || "").trim();
  if (!model || !STT_MODEL_NAME.test(model)) return null;
  const languages = String((env && env.B66_STT_LANGUAGES) || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter((tag) => STT_LANGUAGE_TAG.test(tag))
    .slice(0, 8);
  const silence = Number((env && env.B66_STT_SILENCE_MS) || 650);
  return {
    model,
    languages,
    silenceDurationMs: Number.isFinite(silence) && silence >= 200 && silence <= 10000
      ? Math.round(silence)
      : 650,
    tokenEndpoint: String((env && env.B66_STT_TOKEN_URL) || GEMINI_AUTH_TOKEN_ENDPOINT),
    websocketBase: String((env && env.B66_STT_WS_BASE_URL) || GEMINI_LIVE_WS_BASE)
  };
}

function isoFromSeconds(seconds) {
  return new Date(Date.now() + Math.max(1, Number(seconds) || 1) * 1000).toISOString();
}

/* The canonical signed-in shape is the one padiem-account.js consumes: ok +
   authenticated + session_state. An unreachable auth service denies, it never
   grants. */
async function sessionVerified(request, env, context) {
  const cookie = request.headers.get("cookie");
  if (!context.carriesSessionCookie(cookie)) return false;
  const target = new URL("/api/auth/status", context.chatOrigin);
  const init = {
    method: "GET",
    headers: new Headers({ Accept: "application/json", Cookie: cookie }),
    redirect: "manual"
  };
  let response = null;
  try {
    const binding = env && env.PADIEM_CHAT_SERVICE;
    response = binding && typeof binding.fetch === "function"
      ? await binding.fetch(new Request(target, init))
      : await fetch(target, init);
  } catch (_) {
    return false;
  }
  if (!response || !response.ok) return false;
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    return false;
  }
  return Boolean(payload) && payload.authenticated === true && payload.session_state === "signed_in";
}

const grantName = (value) => (typeof value === "string" && value ? value : null);

export async function handleVoiceToken(request, env, context) {
  const { jsonError, chatOrigin, allowedMutation } = context;
  if (request.method !== "POST") return jsonError("voice_token_method_not_allowed", 405);
  if (!allowedMutation(request)) return jsonError("padiem_origin_rejected", 403);
  const length = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(length) && length > MAX_VOICE_TOKEN_BODY_BYTES) {
    return jsonError("request_too_large", 413);
  }
  const body = await request.text();
  if (body.length > MAX_VOICE_TOKEN_BODY_BYTES) return jsonError("request_too_large", 413);

  const config = configuration(env);
  if (!config) return jsonError("voice_config_unavailable", 503);
  const credential = await readStoredValue(env, "PADIEM_GEMINI_API_KEY");
  if (!credential) return jsonError("voice_credential_binding_unavailable", 503);
  if (!(await sessionVerified(request, env, { chatOrigin, carriesSessionCookie: context.carriesSessionCookie }))) {
    return jsonError("voice_token_unauthenticated", 401);
  }

  const mintedAt = new Date().toISOString();
  const payload = {
    uses: 1,
    expireTime: isoFromSeconds(VOICE_TOKEN_SESSION_SECONDS),
    newSessionExpireTime: isoFromSeconds(VOICE_TOKEN_NEW_SESSION_SECONDS),
    liveConnectConstraints: {
      model: "models/" + config.model,
      config: {
        responseModalities: ["TEXT"],
        inputAudioTranscription: { languageCodes: config.languages, mode: "VERBATIM" },
        realtimeInputConfig: { automaticActivityDetection: { silenceDurationMs: config.silenceDurationMs } }
      }
    }
  };

  let upstream = null;
  try {
    upstream = await fetch(config.tokenEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": credential },
      body: JSON.stringify(payload)
    });
  } catch (_) {
    return jsonError("voice_token_service_unavailable", 502);
  }
  if (!upstream || !upstream.ok) {
    /* The upstream error body is not relayed: it can echo the request, and the
       request carries the credential header. */
    return jsonError("voice_token_denied", 502);
  }
  let granted = null;
  try {
    granted = await upstream.json();
  } catch (_) {
    return jsonError("voice_token_unparsable", 502);
  }
  /* Google documents the grant under token.name but does not publish the full
     response, so the two sibling shapes are read too. No shape match is a failure,
     never a guess. */
  let token = null;
  if (granted && granted.token) token = grantName(granted.token.name) || grantName(granted.token);
  if (!token) token = grantName(granted && granted.name);
  if (!token) return jsonError("voice_token_missing", 502);

  const headers = new Headers({
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store, max-age=0",
    Pragma: "no-cache"
  });
  return new Response(JSON.stringify({
    ok: true,
    token,
    websocketUrl: config.websocketBase,
    model: config.model,
    languageCodes: config.languages,
    transcriptionMode: "VERBATIM",
    silenceDurationMs: config.silenceDurationMs,
    singleUse: true,
    expiresAt: payload.expireTime,
    mintedAt
  }), { status: 200, headers });
}

export const VOICE_TEST_EXPORTS = {
  configuration,
  readStoredValue,
  grantName,
  GEMINI_AUTH_TOKEN_ENDPOINT,
  GEMINI_LIVE_WS_BASE
};
