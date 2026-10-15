/* B66 #3186 STEP 3-A — Cloudflare Pages relay for staff-only approval inbox. */

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const WORKER_PATH = path.join(ROOT, "_worker.js");
const ADMIN_PAGE = path.join(ROOT, "admin-saved-skill-candidates.html");
const ORIGIN = "https://quick-quote-kr.pages.dev";
const CANDIDATE_ID = "b66cand_" + "a".repeat(32);
const calls = [];

function jsonResponse(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

(async function () {
  const { default: worker } = await import("file://" + WORKER_PATH.replace(/\\/g, "/"));
  const originalFetch = globalThis.fetch;
  let mode = "list";
  globalThis.fetch = async (target, init) => {
    const url = String(target);
    calls.push({ url, init });
    if (url.indexOf("/api/b66/admin/saved-skill-candidates/" + CANDIDATE_ID) !== -1) {
      return jsonResponse({ ok: true, candidate: { candidate_id: CANDIDATE_ID, user_id: "usr_" + "a".repeat(32), status: "pending" } });
    }
    if (url.indexOf("/api/b66/admin/saved-skill-candidates") !== -1) {
      return jsonResponse({ ok: true, candidates: [{ candidate_id: CANDIDATE_ID, user_id: "usr_" + "a".repeat(32), status: "pending" }] });
    }
    return jsonResponse({ ok: false, error: { code: "unexpected_upstream" } }, { status: 500 });
  };

  function request(pathname) {
    return new Request(ORIGIN + pathname);
  }

  try {
    // 1. staff-only list is forwarded with bounded limit/status only.
    calls.length = 0;
    let response = await worker.fetch(request("/api/padiem/b66/admin/saved-skill-candidates?limit=7&status=approved"), {
      method: "GET",
      headers: { Cookie: "padiem_session=synthetic" }
    });
    assert.equal(response.status, 200);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://chat.padiem.net/api/b66/admin/saved-skill-candidates?status=approved&limit=7");
    assert.ok(!calls[0].url.includes("owner"), "client-supplied identity must not be forwarded");

    calls.length = 0;
    response = await worker.fetch(request("/api/padiem/b66/admin/saved-skill-candidates?owner=usr_b"), {
      method: "GET",
      headers: { Cookie: "padiem_session=synthetic" }
    });
    assert.equal(response.status, 404, "client-supplied identity must not get past the bridge");
    assert.equal(calls.length, 0, "backend must not be called for unknown bridge query");

    // Invalid status/filter combinations are rejected before the backend.
    for (const query of ["status=invalid", "limit=0", "limit=99", "limit=abc", "bad=1"]) {
      calls.length = 0;
      response = await worker.fetch(request("/api/padiem/b66/admin/saved-skill-candidates?" + query), {
        method: "GET",
        headers: { Cookie: "padiem_session=synthetic" }
      });
      assert.equal(response.status, 404, "invalid query must be refused: " + query);
      assert.equal(calls.length, 0, "backend must not be called for rejected query: " + query);
    }

    // 2. staff-only detail is forwarded by exact skill-candidate ID.
    calls.length = 0;
    response = await worker.fetch(request("/api/padiem/b66/admin/saved-skill-candidates/" + CANDIDATE_ID), {
      method: "GET",
      headers: { Cookie: "padiem_session=synthetic" }
    });
    assert.equal(response.status, 200);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://chat.padiem.net/api/b66/admin/saved-skill-candidates/" + CANDIDATE_ID);

    // 3. POST and unknown IDs are not exposed through this read-only relay.
    const badId = "/api/padiem/b66/admin/saved-skill-candidates/" + "b66cand_" + "z".repeat(32);
    calls.length = 0;
    response = await worker.fetch(request(badId), { method: "GET", headers: { Cookie: "padiem_session=synthetic" } });
    assert.equal(response.status, 404);
    assert.equal(calls.length, 0);

    const env = { ASSETS: { fetch: async () => new Response("asset", { status: 200 }) } };
    const postResponse = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/admin/saved-skill-candidates/" + CANDIDATE_ID, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: "padiem_session=synthetic" },
      body: JSON.stringify({ action: "approve" })
    }), env);
    assert.equal(postResponse.status, 404, "approval execution must not be reachable through this read-only relay");

    // 4. UI source must not include approval/rejection controls.
    const html = fs.readFileSync(ADMIN_PAGE, "utf8");
    assert.ok(!/\bapprove\b/i.test(html), "read-only inbox HTML must not expose an approve control");
    assert.ok(!/\breject\b/i.test(html), "read-only inbox HTML must not expose a reject control");
  } finally {
    globalThis.fetch = originalFetch;
  }
  console.log("B66_ADMIN_SKILL_CANDIDATE_INBOX_RELAY=PASS");
  console.log("STAFF_READ_ONLY_DECISION_CONTROLS=0");
})();
