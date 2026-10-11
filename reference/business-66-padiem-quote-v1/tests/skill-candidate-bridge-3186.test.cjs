/* B66 #3186 — Cloudflare Pages `_worker.js` 의 승인 요청 브리지 계약.

   고객은 승인 *요청* 만 보낼 수 있다. 브리지에는 승인/거부 경로가 없고,
   경로·limit·행 id 형태만 경계하며 owner/workspace 는 서버가 도출한다. */

const assert = require("node:assert");
const path = require("node:path");

const WORKER_PATH = path.join(__dirname, "..", "_worker.js");
const ORIGIN = "https://quick-quote-kr.pages.dev";
const CANDIDATE_ID = "b66cand_" + "a".repeat(32);

const calls = [];

function jsonResponse(payload, init) {
  return new Response(JSON.stringify(payload), Object.assign({
    status: 200,
    headers: { "Content-Type": "application/json" }
  }, init || {}));
}

(async function () {
  const { default: worker } = await import("file://" + WORKER_PATH.replace(/\\/g, "/"));
  const originalFetch = globalThis.fetch;
  const env = {
    ASSETS: { fetch: () => new Response("asset", { status: 200 }) }
  };
  globalThis.fetch = async (target, init) => {
    const url = String(target);
    calls.push({ url, init });
    if (url.endsWith("/api/b66/saved-skill-candidates/" + CANDIDATE_ID)) {
      return jsonResponse({ ok: true, candidate: { candidate_id: CANDIDATE_ID, status: "pending" } });
    }
    if (url.indexOf("/api/b66/saved-skill-candidates") !== -1) {
      return jsonResponse({ ok: true, candidate: { candidate_id: CANDIDATE_ID, status: "pending" }, duplicate: false });
    }
    return jsonResponse({ ok: false, error: { code: "unexpected_upstream" } }, { status: 500 });
  };

  try {
    function request(pathname, options) {
      return new Request(ORIGIN + pathname, options);
    }
    function sessionHeaders(extra) {
      return Object.assign({
        "Content-Type": "application/json",
        "Cookie": "padiem_session=synthetic",
        "Origin": ORIGIN
      }, extra || {});
    }

    // 1. 승인 요청 제출은 정확한 upstream 경로로 전달된다.
    calls.length = 0;
    const submitted = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates", {
      method: "POST",
      headers: sessionHeaders(),
      body: JSON.stringify({ client_ref: "manual-0123456789abcdef01234567-abcdef01", candidate: { schemaVersion: 1 } })
    }), env);
    assert.equal(submitted.status, 200);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://chat.padiem.net/api/b66/saved-skill-candidates");
    assert.equal(calls[0].init.method, "POST");
    assert.match(submitted.headers.get("cache-control"), /no-store/);

    // 2. 목록 조회는 bounded limit 만 전달한다.
    calls.length = 0;
    const listed = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates?limit=20", {
      method: "GET",
      headers: { "Cookie": "padiem_session=synthetic" }
    }), env);
    assert.equal(listed.status, 200);
    assert.equal(calls[0].url, "https://chat.padiem.net/api/b66/saved-skill-candidates?limit=20");

    for (const query of ["limit=0", "limit=99", "limit=abc"]) {
      const reply = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates?" + query, {
        method: "GET",
        headers: { "Cookie": "padiem_session=synthetic" }
      }), env);
      assert.equal(reply.status, 404, "unbounded query must be refused: " + query);
      assert.ok((await reply.json()).error.code === "padiem_route_not_allowed");
    }

    /* 추가 쿼리는 전달되지 않는다. 브리지는 경계된 limit 만 재구성해 보낸다. */
    calls.length = 0;
    const extra = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates?limit=2&owner=usr_b", {
      method: "GET",
      headers: { "Cookie": "padiem_session=synthetic" }
    }), env);
    assert.equal(extra.status, 200);
    assert.equal(calls[0].url, "https://chat.padiem.net/api/b66/saved-skill-candidates?limit=2");
    assert.ok(calls[0].url.indexOf("owner") === -1, "client-supplied owner must never be forwarded");

    // 3. 상세 조회는 후보 행 id 형태만 통과시킨다.
    calls.length = 0;
    const detail = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates/" + CANDIDATE_ID, {
      method: "GET",
      headers: { "Cookie": "padiem_session=synthetic" }
    }), env);
    assert.equal(detail.status, 200);
    assert.equal(calls[0].url, "https://chat.padiem.net/api/b66/saved-skill-candidates/" + CANDIDATE_ID);

    for (const badId of ["not-an-id", "b66skill_" + "a".repeat(32), CANDIDATE_ID + "/approve", "..", CANDIDATE_ID.toUpperCase()]) {
      const reply = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates/" + badId, {
        method: "GET",
        headers: { "Cookie": "padiem_session=synthetic" }
      }), env);
      assert.equal(reply.status, 404, "non-candidate row id must be refused: " + badId);
    }

    // 4. 고객용 승인/거부 경로는 브리지에 존재하지 않는다.
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      for (const suffix of ["", "/approve", "/reject", "/decision"]) {
        const reply = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates/" + CANDIDATE_ID + suffix, {
          method: method,
          headers: sessionHeaders(),
          body: method === "DELETE" ? undefined : JSON.stringify({ status: "approved" })
        }), env);
        assert.equal(reply.status, 404, method + " " + suffix + " must not be bridged");
      }
    }

    // 5. 쿠키가 실린 교차 출처 변경 요청은 거부된다(기존 CSRF 경계 재사용).
    const crossOrigin = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cookie": "padiem_session=synthetic",
        "Origin": "https://evil.example.test"
      },
      body: JSON.stringify({})
    }), env);
    assert.equal(crossOrigin.status, 403);
    assert.equal((await crossOrigin.json()).error.code, "padiem_origin_rejected");

    // 6. 상한을 넘는 본문은 전달 전에 거부된다.
    const oversized = await worker.fetch(request("/api/padiem/b66/saved-skill-candidates", {
      method: "POST",
      headers: sessionHeaders(),
      body: JSON.stringify({ blob: "x".repeat(40 * 1024) })
    }), env);
    assert.equal(oversized.status, 413);
    assert.equal((await oversized.json()).error.code, "request_too_large");

    console.log("B66_SKILL_CANDIDATE_BRIDGE=PASS");
    console.log("CANDIDATE_SUBMIT_ROUTE=BOUNDED");
    console.log("CANDIDATE_APPROVE_ROUTE_IN_BRIDGE=0");
    console.log("CANDIDATE_ROW_ID_SHAPE_ENFORCED=YES");
    console.log("CANDIDATE_CROSS_ORIGIN_MUTATION=REJECTED");
    console.log("CANDIDATE_OVERSIZED_BODY=REJECTED");
  } finally {
    globalThis.fetch = originalFetch;
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
