/**
 * LoveTree auth caller — 러브트리 제품의 세션 **폐기**만 허용된 중계.
 *
 * 재사용한 기존 구현: `apps/lovetree-authority-caller/worker.mjs`(그 자체가
 * `apps/padiem-ai-engine/preview-caller/worker.mjs`의 caller 형태를 따랐다) —
 * service binding으로 private 권위에 닿는 caller Worker, 상수시간 bearer, 크기 상한,
 * 실패 시 닫힌 JSON. 새 형식은 만들지 않는다.
 *
 * 경계:
 * - 서버 간 인증(COM2 → 이 중계): `authorization: Bearer <LOVETREE_CALLER_SECRET>`. 서비스 신원이지 사용자 신원이 아니다.
 * - 사용자 세션:폐기할 canonical session id는 중계가 검증된 것으로 본다. 권위가 제품 소속을 확인한다
 *   (`identity_authority_worker.py:264-281`은 `product_id` + `session_id`만 받고 행이 그 제품의 것이 아니면 닫힌다).
 *
 * **발급(mint)은 이 중계에서 열리지 않는다.** `resolve_or_create_product_link`와
 * `establish_auth_session`을 부르려면 "러브트리 서버가 주장하는 provider_subject를
 * 누가 검증했는가"에 대한 Owner·CTO 결정이 선행돼야 한다. 그 결정 없이 caller가
 * 임의 사용자 ID로 세션을 만들 수 있게 두면 이 중계가 신원 발행소가 된다.
 * 그래서 `/mint-session`은 어떤 입력에도 501로 닫히고, 결정이 나면 그 결정에 맞는
 * 검증된 근거(예: 이미 확인된 로그인 권위에서 발급한 1회성 handoff ticket)를 받아 여는
 * 별도 변경으로 온다.
 */

export const REVOKE_PATH = "/revoke-session";
export const MINT_PATH = "/mint-session";
export const AUTH_CHECK_PATH = "/auth-check";
export const LOVETREE_PRODUCT_ID = "lovetree-4-0";
export const MAX_REQUEST_BYTES = 4096;

const CANONICAL_SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" }
  });
}

function constantTimeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const len = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < len; i += 1) {
    diff |= (i < a.length ? a.charCodeAt(i) : 0) ^ (i < b.length ? b.charCodeAt(i) : 0);
  }
  return diff === 0;
}

function callerState(request, env) {
  const secret = env?.LOVETREE_CALLER_SECRET;
  if (!secret) return "unavailable";
  const header = request.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  return token && constantTimeEqual(token, secret) ? "ok" : "denied";
}

async function readClosedBody(request) {
  const reader = request.body?.getReader?.();
  if (!reader) return null;
  let total = 0;
  const chunks = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value?.byteLength ?? 0;
      if (total > MAX_REQUEST_BYTES) return null;
      chunks.push(value);
    }
  } catch {
    return null;
  } finally {
    try { reader.releaseLock(); } catch { /* 이미 닫힌 리더는 정리 대상이 아니다 */ }
  }
  try {
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await new Blob(chunks).arrayBuffer()));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function handleRequest(request, env) {
  const path = new URL(request.url).pathname;

  if (path === "/health" && request.method === "GET") {
    return jsonResponse(200, { ok: true, service: "lovetree-auth-caller", status: "ready", mint: "closed" });
  }

  if (path === AUTH_CHECK_PATH && (request.method === "GET" || request.method === "POST")) {
    const state = callerState(request, env);
    if (state === "denied") return jsonResponse(401, { ok: false, error: { code: "unauthorized", message: "Invalid or missing caller bearer token." } });
    if (state === "unavailable") return jsonResponse(503, { ok: false, error: { code: "caller_credential_unavailable", message: "LOVETREE_CALLER_SECRET is not available." } });
    if (!env?.IDENTITY_AUTHORITY?.revoke_auth_session) {
      return jsonResponse(503, { ok: false, error: { code: "authority_binding_unavailable", message: "IDENTITY_AUTHORITY binding is not available." } });
    }
    return jsonResponse(200, { ok: true, status: "authenticated", methods: ["revoke-session"], mint: "closed" });
  }

  // 발급은 결정 전까지 어떤 입력에도 닫힌다.
  if (path === MINT_PATH) {
    return jsonResponse(501, {
      ok: false,
      error: {
        code: "mint_policy_undecided",
        message: "LoveTree session minting needs the reviewed login-evidence source; this relay never accepts a caller-asserted identity."
      }
    });
  }

  if (path !== REVOKE_PATH || request.method !== "POST") {
    return jsonResponse(404, { ok: false, error: { code: "not_found", message: "No such endpoint." } });
  }

  const state = callerState(request, env);
  if (state === "denied") return jsonResponse(401, { ok: false, error: { code: "unauthorized", message: "Invalid or missing caller bearer token." } });
  if (state === "unavailable") return jsonResponse(503, { ok: false, error: { code: "caller_credential_unavailable", message: "LOVETREE_CALLER_SECRET is not available." } });

  const body = await readClosedBody(request);
  if (!body || Object.keys(body).length !== 1 || typeof body.session_id !== "string" || !CANONICAL_SESSION_ID.test(body.session_id)) {
    return jsonResponse(400, { ok: false, error: { code: "invalid_request", message: "Exactly one bounded session_id is required." } });
  }
  if (!env?.IDENTITY_AUTHORITY?.revoke_auth_session) {
    return jsonResponse(503, { ok: false, error: { code: "authority_unavailable", message: "Identity authority is unavailable." } });
  }

  let answer;
  try {
    // 제품 ID는 여기서 고정한 값만 보낸다. 호출자가 제품이나 주체를 주장할 수 없다.
    answer = await env.IDENTITY_AUTHORITY.revoke_auth_session({ product_id: LOVETREE_PRODUCT_ID, session_id: body.session_id });
  } catch {
    return jsonResponse(503, { ok: false, error: { code: "authority_unavailable", message: "Identity authority could not be reached." } });
  }

  if (answer?.ok !== true || answer?.session?.state !== "revoked" || answer?.session?.session_id !== body.session_id) {
    return jsonResponse(401, { ok: false, error: { code: "session_not_revoked", message: "The authority did not revoke a LoveTree session for that id." } });
  }
  return jsonResponse(200, { ok: true, revoked: { session_id: answer.session.session_id, product_id: answer.session.product_id, state: answer.session.state } });
}

export default {
  async fetch(request, env) {
    return handleRequest(request, env);
  }
};
