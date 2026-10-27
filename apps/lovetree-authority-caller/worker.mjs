/**
 * LoveTree authority caller — COM2 저장 API와 private Control Plane 사이의 최소 중계.
 *
 * 재사용한 기존 구현: `apps/padiem-ai-engine/preview-caller/worker.mjs`
 * (service binding으로 private worker를 부르는 caller Worker, constant-time bearer 확인,
 *  /health·/auth-check, 응답 크기 상한, 실패 시 fail-closed JSON).
 *
 * 경계 두 개를 구분한다.
 * - 서버 간 인증(COM2 → 이 중계): `authorization: Bearer <LOVETREE_CALLER_SECRET>`. 서비스 자격이지 사용자 신원이 아니다.
 * - 사용자 인증(세션 id): 중계가 읽기만 두 RPC로 물어보는 값일 뿐, 여기서 진위를 만들지 않는다.
 *   서명 확인·발급·폐기는 러브트리 서비스 쪽 credential.verify와 Control Plane의 소유다.
 *
 * 불변:
 * - Control Plane 자체의 공개 HTTP 표면은 그대로다(이 중계가 service binding 하나로 닿는다).
 * - 읽기 전용 RPC 두 개만 포워딩한다. `resolve_or_create_product_link`·`establish_auth_session`
 *   같은 쓰기 RPC는 이 경로로 부를 수 없다(로그인 후 세션 발급은 별도 후속 연결).
 * - D1/KV/R2 바인딩 0개, 사용자 기록 본문은 통과시키지 않는다.
 */

export const LOVETREE_PRODUCT_ID = "lovetree-4-0";
export const RESOLVE_SESSION_PATH = "/resolve-session";
export const AUTH_CHECK_PATH = "/auth-check";
export const MAX_REQUEST_BYTES = 4096;
export const MAX_RESPONSE_BYTES = 64 * 1024;

const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
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

function callerAuthenticated(request, env) {
  const secret = env?.LOVETREE_CALLER_SECRET;
  if (!secret) return "unavailable";
  const header = request.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  return token && constantTimeEqual(token, secret) ? "ok" : "denied";
}

async function readBoundedJson(request) {
  const reader = request.body?.getReader?.();
  if (!reader) return null;
  const chunks = [];
  let total = 0;
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
  const text = new TextDecoder("utf-8").decode(await new Blob(chunks).arrayBuffer());
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * 두 개의 읽기 전용 RPC만 호출해 확인된 신원을 좁은 형태로 돌려준다.
 * 권위가 active·user·미만료·자기 제품이라고 답한 값만 통과한다.
 */
export async function resolveIdentity(authority, { sessionId, now = () => Date.now() }) {
  if (!authority?.resolve_auth_session || !authority?.resolve_product_user_for_subject) {
    return { ok: false, status: 503, code: "authority_unavailable" };
  }
  const sessionAnswer = await authority.resolve_auth_session({ session_id: sessionId });
  const session = sessionAnswer?.ok === true ? sessionAnswer.session : null;
  if (!session || session.session_id !== sessionId || session.product_id !== LOVETREE_PRODUCT_ID) {
    return { ok: false, status: 401, code: "unauthenticated" };
  }
  if (session.state !== "active" || session.subject?.subject_type !== "user") {
    return { ok: false, status: 401, code: "unauthenticated" };
  }
  const expires = Date.parse(session.expires_at ?? "");
  if (!Number.isFinite(expires) || expires <= now()) return { ok: false, status: 401, code: "unauthenticated" };

  const subjectId = session.subject.subject_id;
  const linkAnswer = await authority.resolve_product_user_for_subject({
    product_id: LOVETREE_PRODUCT_ID,
    canonical_subject_id: subjectId
  });
  if (linkAnswer?.ok !== true || typeof linkAnswer.product_user_id !== "string") {
    return { ok: false, status: 401, code: "unauthenticated" };
  }
  return { ok: true, identity: { session_id: sessionId, product_id: LOVETREE_PRODUCT_ID, subject_id: subjectId, expires_at: session.expires_at } };
}

export async function handleRequest(request, env) {
  const path = new URL(request.url).pathname;

  if (path === "/health" && request.method === "GET") {
    return jsonResponse(200, { ok: true, service: "lovetree-authority-caller", status: "ready" });
  }

  if (path === AUTH_CHECK_PATH && (request.method === "GET" || request.method === "POST")) {
    const state = callerAuthenticated(request, env);
    if (state === "denied") return jsonResponse(401, { ok: false, error: { code: "unauthorized", message: "Invalid or missing caller bearer token." } });
    if (state === "unavailable") return jsonResponse(503, { ok: false, error: { code: "caller_credential_unavailable", message: "LOVETREE_CALLER_SECRET is not available." } });
    if (!env?.IDENTITY_AUTHORITY?.resolve_auth_session) {
      return jsonResponse(503, { ok: false, error: { code: "authority_binding_unavailable", message: "IDENTITY_AUTHORITY binding is not available." } });
    }
    return jsonResponse(200, { ok: true, status: "authenticated", read_only_methods: 2 });
  }

  if (path !== RESOLVE_SESSION_PATH || request.method !== "POST") {
    return jsonResponse(404, { ok: false, error: { code: "not_found", message: "No such endpoint." } });
  }

  const state = callerAuthenticated(request, env);
  if (state === "denied") return jsonResponse(401, { ok: false, error: { code: "unauthorized", message: "Invalid or missing caller bearer token." } });
  if (state === "unavailable") return jsonResponse(503, { ok: false, error: { code: "caller_credential_unavailable", message: "LOVETREE_CALLER_SECRET is not available." } });

  const body = await readBoundedJson(request);
  const closed = body && Object.keys(body).length === 1 && typeof body.session_id === "string" && SESSION_ID.test(body.session_id);
  if (!closed) return jsonResponse(400, { ok: false, error: { code: "invalid_request", message: "Exactly one bounded session_id is required." } });

  try {
    const result = await resolveIdentity(env?.IDENTITY_AUTHORITY, { sessionId: body.session_id });
    if (!result.ok) {
      return jsonResponse(result.status, { ok: false, error: { code: result.code, message: result.status === 503 ? "Identity authority is unavailable." : "Session is not a verified LoveTree identity." } });
    }
    const payload = JSON.stringify({ ok: true, identity: result.identity });
    if (new TextEncoder().encode(payload).length > MAX_RESPONSE_BYTES) {
      return jsonResponse(502, { ok: false, error: { code: "authority_response_too_large", message: "Identity authority response exceeded the safety limit." } });
    }
    return jsonResponse(200, { ok: true, identity: result.identity });
  } catch {
    return jsonResponse(503, { ok: false, error: { code: "authority_unavailable", message: "Identity authority could not be reached." } });
  }
}

export default {
  async fetch(request, env) {
    return handleRequest(request, env);
  }
};
