/**
 * LoveTree auth caller — 러브트리 제품의 세션 **폐기**와 **1회용 handoff 발급**만 허용된 중계.
 *
 * 재사용한 기존 구현: `apps/lovetree-authority-caller/worker.mjs`(그 자체가
 * `apps/padiem-ai-engine/preview-caller/worker.mjs`의 caller 형태를 따랐다) —
 * service binding으로 private 권위에 닿는 caller Worker, 상수시간 bearer, 크기 상한,
 * 실패 시 닫힌 JSON. 상태 전이는 `apps/padiem-chat/app/android_auth_store.py`의
 * 조건부 UPDATE 한 문장 방식 그대로이고, 표의 정의는 migration 073이다.
 *
 * 경계:
 * - 서버 간 인증(COM2 → 이 중계): `authorization: Bearer <LOVETREE_CALLER_SECRET>`. 서비스 신원이지 사용자 신원이 아니다.
 * - 사용자 세션: 폐기할 canonical session id는 권위가 제품 소속을 확인한다
 *   (`identity_authority_worker.py:264-281`은 `product_id` + `session_id`만 받고 행이 그 제품의 것이 아니면 닫힌다).
 * - 발급 근거: caller가 보낸 것은 **handoff 표와 그 표를 부른 로그인 요청의 해시** 두 값뿐이다.
 *   제품·수신자·로그인 요청·검증된 신원은 이미 확인된 로그인(`lovetree_login_handoffs`)이 행에 써 놓은
 *   값만 쓴다. 호출자가 provider_subject·사용자 ID·제품을 주장하는 경로는 어떤 요청에도 없고,
 *   해시가 행에 적힌 로그인 요청과 다르면 표는 소비조차 되지 않는다.
 *
 * 표는 단일 사용이다. 클레임은 조건부 UPDATE 한 문장이라 늦거나 반복된 요청은 두 번째 발급을 만들지
 * 못하고, 클레임 이후 발급이 실패하면 그 표는 소진된 채로 남는다 — 재시도는 로그인을 처음부터 다시 해야 한다.
 */

export const REVOKE_PATH = "/revoke-session";
export const MINT_PATH = "/mint-session";
export const AUTH_CHECK_PATH = "/auth-check";
export const LOVETREE_PRODUCT_ID = "lovetree-4-0";
export const LOVETREE_HANDOFF_RECIPIENT = "lovetree-auth-caller";
export const MAX_REQUEST_BYTES = 4096;
export const SESSION_TTL_SECONDS = 3600;

const CANONICAL_SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SHA256_HEX = /^[0-9a-f]{64}$/;
const PRODUCT_USER_ID = /^usr_[A-Za-z0-9_-]{1,80}$/;
const AUTH_PROVIDERS = new Set(["google", "password"]);
const HANDOFF_COLUMNS =
  "ticket_id, product_id, recipient, state_sha256, status, pending_user_id, auth_provider, provider_subject, created_at, updated_at, expires_at";

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

// migration 058/073의 타임스탬프와 같은 고정 UTC 형식. 밀리초가 섞이면 문자열 비교가 어긋난다.
function nowIso(at) {
  return new Date(at).toISOString().slice(0, 19) + "Z";
}

async function claimHandoff(db, ticketId, requestDigest, at) {
  const statement = db.prepare(
    "UPDATE lovetree_login_handoffs "
    + "SET status='claimed', claimed_at=?, updated_at=? "
    + "WHERE ticket_id=? AND product_id = ? AND recipient = ? AND state_sha256 = ? AND status='ready' AND expires_at > ? "
    + `RETURNING ${HANDOFF_COLUMNS}`
  );
  const row = await statement
    .bind(nowIso(at), nowIso(at), ticketId, LOVETREE_PRODUCT_ID, LOVETREE_HANDOFF_RECIPIENT, requestDigest, nowIso(at))
    .first();
  const record = row?.to_py?.() ?? row;
  if (!record || typeof record !== "object") return null;
  if (record.status !== "claimed" || record.product_id !== LOVETREE_PRODUCT_ID || record.recipient !== LOVETREE_HANDOFF_RECIPIENT) return null;
  if (!PRODUCT_USER_ID.test(record.pending_user_id ?? "") || !AUTH_PROVIDERS.has(record.auth_provider)) return null;
  if (typeof record.provider_subject !== "string" || !record.provider_subject.trim() || record.provider_subject.length > 255) return null;
  return record;
}

async function mintSession(request, env, at) {
  const state = callerState(request, env);
  if (state === "denied") return jsonResponse(401, { ok: false, error: { code: "unauthorized", message: "Invalid or missing caller bearer token." } });
  if (state === "unavailable") return jsonResponse(503, { ok: false, error: { code: "caller_credential_unavailable", message: "LOVETREE_CALLER_SECRET is not available." } });

  const body = await readClosedBody(request);
  const ticket = body?.handoff_ticket;
  const digest = body?.login_request_sha256;
  if (!body || Object.keys(body).length !== 2 || typeof ticket !== "string" || !CANONICAL_SESSION_ID.test(ticket)
    || typeof digest !== "string" || !SHA256_HEX.test(digest)) {
    return jsonResponse(400, { ok: false, error: { code: "invalid_request", message: "Exactly one bounded handoff_ticket and its login request digest are required." } });
  }
  if (!env?.LOVETREE_LOGIN_DB) {
    return jsonResponse(503, { ok: false, error: { code: "handoff_store_unavailable", message: "LOVETREE_LOGIN_DB is not bound." } });
  }
  if (!env?.IDENTITY_AUTHORITY?.resolve_or_create_product_link || !env?.IDENTITY_AUTHORITY?.establish_auth_session) {
    return jsonResponse(503, { ok: false, error: { code: "authority_unavailable", message: "Identity authority is unavailable." } });
  }

  // 표 소비는 이 한 문장에서 끝난다. 지금 요청의 해시가 행에 적힌 해시와 다르면
  // 행은 그대로 남는다(WHERE가 소비 조건이라, 남의 요청으로는 표가 소모되지 않는다).
  let claimed;
  try {
    claimed = await claimHandoff(env.LOVETREE_LOGIN_DB, ticket, digest, at);
  } catch {
    return jsonResponse(503, { ok: false, error: { code: "handoff_store_unavailable", message: "The login handoff store could not be reached." } });
  }
  if (!claimed) {
    // 존재·상태·요청 결합 중 어느 실패인지 가르지 않고 같은 코드로 닫는다.
    return jsonResponse(401, { ok: false, error: { code: "invalid_handoff", message: "That login handoff is not claimable." } });
  }

  const authenticatedAt = new Date(at);
  const notAfter = new Date(at + SESSION_TTL_SECONDS * 1000);
  let issued;
  let subjectId;
  try {
    const linked = await env.IDENTITY_AUTHORITY.resolve_or_create_product_link({
      product_id: LOVETREE_PRODUCT_ID,
      product_user_id: claimed.pending_user_id,
      auth_provider: claimed.auth_provider,
      provider_subject: claimed.provider_subject
    });
    subjectId = linked?.link?.canonical_subject_id;
    if (linked?.ok !== true || !CANONICAL_SESSION_ID.test(subjectId ?? "") || linked?.link?.state !== "active") {
      return jsonResponse(503, { ok: false, error: { code: "session_not_minted", message: "The identity authority did not activate a LoveTree subject." } });
    }
    issued = await env.IDENTITY_AUTHORITY.establish_auth_session({
      product_id: LOVETREE_PRODUCT_ID,
      subject: { subject_type: "user", subject_id: subjectId },
      authenticated_at: authenticatedAt.toISOString(),
      not_after: notAfter.toISOString()
    });
  } catch {
    return jsonResponse(503, { ok: false, error: { code: "authority_unavailable", message: "Identity authority could not be reached." } });
  }

  const session = issued?.session;
  const expiresAt = Date.parse(session?.expires_at ?? "");
  const trustworthy = issued?.ok === true
    && CANONICAL_SESSION_ID.test(session?.session_id ?? "")
    && session?.product_id === LOVETREE_PRODUCT_ID
    && session?.state === "active"
    && session?.subject?.subject_type === "user"
    && session?.subject?.subject_id === subjectId;
  if (!session || !trustworthy || !Number.isFinite(expiresAt) || expiresAt <= at) {
    return jsonResponse(503, { ok: false, error: { code: "session_not_minted", message: "The authority did not establish a LoveTree session." } });
  }
  // 응답은 최소한만: 발급 사실과 세션 식별자. 표에 담긴 신원을 호출자에게 되돌려 주지 않는다.
  return jsonResponse(200, {
    ok: true,
    session: { session_id: session.session_id, product_id: session.product_id, subject_id: session.subject.subject_id, expires_at: session.expires_at }
  });
}

export async function handleRequest(request, env, context = {}) {
  const path = new URL(request.url).pathname;
  const at = context?.clock?.() ?? Date.now();

  if (path === "/health" && request.method === "GET") {
    return jsonResponse(200, { ok: true, service: "lovetree-auth-caller", status: "ready", mint: "durable-handoff" });
  }

  if (path === AUTH_CHECK_PATH && (request.method === "GET" || request.method === "POST")) {
    const state = callerState(request, env);
    if (state === "denied") return jsonResponse(401, { ok: false, error: { code: "unauthorized", message: "Invalid or missing caller bearer token." } });
    if (state === "unavailable") return jsonResponse(503, { ok: false, error: { code: "caller_credential_unavailable", message: "LOVETREE_CALLER_SECRET is not available." } });
    if (!env?.IDENTITY_AUTHORITY?.revoke_auth_session) {
      return jsonResponse(503, { ok: false, error: { code: "authority_binding_unavailable", message: "IDENTITY_AUTHORITY binding is not available." } });
    }
    return jsonResponse(200, { ok: true, status: "authenticated", methods: ["revoke-session", "mint-session"], mint: "durable-handoff" });
  }

  if (path === MINT_PATH) {
    if (request.method !== "POST") return jsonResponse(405, { ok: false, error: { code: "method_not_allowed", message: "Minting needs POST." } });
    return mintSession(request, env, at);
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
  async fetch(request, env, ctx) {
    return handleRequest(request, env, ctx);
  }
};
