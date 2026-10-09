import assert from "node:assert/strict";
import worker from "../_worker.js";

const originalFetch = globalThis.fetch;
const calls = [];
const ASSET_ID = "b66asset_" + "a".repeat(32);

function json(payload, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", "application/json");
  return new Response(JSON.stringify(payload), { ...init, headers });
}

globalThis.fetch = async (target, init = {}) => {
  const url = String(target);
  const headers = init.headers instanceof Headers ? init.headers : new Headers(init.headers || {});
  calls.push({ url, init, headers });

  if (url.endsWith("/api/auth/password/login")) {
    return json(
      { ok: true, user: { id: "usr_test" } },
      {
        status: 200,
        headers: {
          "Set-Cookie": "padiem_session=opaque-test-token; Path=/; HttpOnly; Secure; SameSite=Lax"
        }
      }
    );
  }
  if (url.endsWith("/api/auth/status")) {
    return json({
      authenticated: true,
      session_state: "signed_in",
      user: { id: "usr_test", name: "Test User" }
    });
  }
  if (url.endsWith("/api/b66/saved-skills?limit=20")) {
    return json({ ok: true, skills: [] });
  }
  if (url.endsWith("/api/b66/quote/interpret")) {
    const rawBody = init.body instanceof ArrayBuffer
      ? new TextDecoder().decode(init.body)
      : String(init.body || "");
    if (rawBody.includes("bounded-upstream-class-input")) {
      return json(
        { ok: false, error: { code: "quote_interpretation_failed", message: "견적 요청을 해석하지 못했습니다." } },
        {
          status: 502,
          headers: {
            "X-B66-Upstream-Class": "upstream_timeout",
            "X-B66-Interpret-Failure-Stage": "interpreter_exception",
            "X-B66-Interpret-Exception-Family": "type_error",
            "X-Internal-Debug": "must-not-relay"
          }
        }
      );
    }
    return json(
      { ok: false, error: { code: "quote_input_unrecognized", message: "견적 입력값을 확인해 주세요." } },
      {
        status: 422,
        headers: {
          "X-B66-Rejection-Reason": "invalid_number",
          "X-B66-Rejection-Path": "items[1].unitPrice",
          "X-B66-Rejection-Type": "string",
          "X-Internal-Debug": "must-not-relay"
        }
      }
    );
  }
  if (url.endsWith("/api/b66/assets/" + ASSET_ID)) {
    return new Response(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), {
      status: 200,
      headers: { "Content-Type": "image/png", "Cache-Control": "private, no-store" }
    });
  }
  if (url.includes("/api/b66/quote/preview-base?saved_skill_id=")) {
    return new Response(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), {
      status: 200,
      headers: { "Content-Type": "image/png", "Cache-Control": "private, no-store" }
    });
  }
  if (url.endsWith("/api/b66/quote/pdf")) {
    return new Response("%PDF-1.7\nsynthetic-test", {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="quote-test.pdf"',
        "X-Internal-Debug": "must-not-relay"
      }
    });
  }
  if (url.endsWith("/auth/google/start")) {
    return new Response(null, {
      status: 302,
      headers: { "Location": "https://accounts.google.com/o/oauth2/auth?provider=google" }
    });
  }
  if (url.endsWith("/auth/google/callback")) {
    return new Response(null, { status: 302, headers: { "Location": "/" } });
  }
  throw new Error("unexpected upstream: " + url);
};

try {
  const assets = { fetch() { throw new Error("assets must not receive bridge routes"); } };
  const env = { ASSETS: assets };

  const login = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/password/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer browser-forged"
      },
      body: JSON.stringify({ identifier: "demo@example.test", password: "not-a-real-secret" })
    }),
    env
  );
  assert.equal(login.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://chat.padiem.net/api/auth/password/login");
  assert.equal(calls[0].headers.get("authorization"), null);
  assert.equal(calls[0].headers.get("cookie"), null);
  assert.match(login.headers.get("set-cookie") || "", /^padiem_session=/);
  assert.match(login.headers.get("set-cookie") || "", /HttpOnly/i);
  assert.match(login.headers.get("set-cookie") || "", /Secure/i);

  const status = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/status", {
      headers: {
        "Cookie": "padiem_session=opaque-test-token",
        "Authorization": "Bearer browser-forged"
      }
    }),
    env
  );
  assert.equal(status.status, 200);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, "https://chat.padiem.net/api/auth/status");
  assert.equal(calls[1].headers.get("cookie"), "padiem_session=opaque-test-token");
  assert.equal(calls[1].headers.get("authorization"), null);
  assert.equal(calls[1].headers.get("x-b66-origin"), "https://quick-quote-kr.pages.dev");

  const list = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/saved-skills?limit=20", {
      headers: { "Cookie": "padiem_session=opaque-test-token" }
    }),
    env
  );
  assert.equal(list.status, 200);
  assert.equal(calls.length, 3);
  assert.equal(calls[2].url, "https://chat.padiem.net/api/b66/saved-skills?limit=20");

  const rejectedQuote = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cookie": "padiem_session=opaque-test-token",
        "Origin": "https://quick-quote-kr.pages.dev"
      },
      body: JSON.stringify({
        saved_skill_id: "b66skill_" + "c".repeat(32),
        message: "bounded-test-input"
      })
    }),
    env
  );
  assert.equal(rejectedQuote.status, 422);
  assert.equal(rejectedQuote.headers.get("x-b66-rejection-reason"), "invalid_number");
  assert.equal(rejectedQuote.headers.get("x-b66-rejection-path"), "items[1].unitPrice");
  assert.equal(rejectedQuote.headers.get("x-b66-rejection-type"), "string");
  assert.equal(rejectedQuote.headers.get("x-internal-debug"), null);
  assert.equal(calls.length, 4);
  assert.equal(calls[3].url, "https://chat.padiem.net/api/b66/quote/interpret");
  assert.equal(calls[3].headers.get("origin"), "https://chat.padiem.net");

  const privateAsset = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/assets/" + ASSET_ID, {
      headers: { "Cookie": "padiem_session=opaque-test-token" }
    }),
    env
  );
  assert.equal(privateAsset.status, 200);
  assert.equal(privateAsset.headers.get("content-type"), "image/png");
  assert.equal(calls.length, 5);
  assert.equal(calls[4].url, "https://chat.padiem.net/api/b66/assets/" + ASSET_ID);
  assert.equal(calls[3].headers.get("cookie"), "padiem_session=opaque-test-token");

  const previewSkillId = "b66skill_" + "c".repeat(32);
  const previewBase = await worker.fetch(
    new Request(
      "https://quick-quote-kr.pages.dev/api/padiem/b66/quote/preview-base?saved_skill_id=" + previewSkillId,
      { headers: { "Cookie": "padiem_session=opaque-test-token" } }
    ),
    env
  );
  assert.equal(previewBase.status, 200);
  assert.equal(previewBase.headers.get("content-type"), "image/png");
  assert.equal(calls.length, 6);
  assert.equal(
    calls[5].url,
    "https://chat.padiem.net/api/b66/quote/preview-base?saved_skill_id=" + previewSkillId
  );
  assert.equal(calls[5].headers.get("accept"), "image/png,application/json");
  assert.equal(calls[5].headers.get("cookie"), "padiem_session=opaque-test-token");

  const upstreamFailure = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cookie": "padiem_session=opaque-test-token",
        "Origin": "https://quick-quote-kr.pages.dev"
      },
      body: JSON.stringify({
        saved_skill_id: "b66skill_" + "c".repeat(32),
        message: "bounded-upstream-class-input"
      })
    }),
    env
  );
  assert.equal(upstreamFailure.status, 502);
  assert.equal(upstreamFailure.headers.get("x-b66-upstream-class"), "upstream_timeout");
  assert.equal(upstreamFailure.headers.get("x-b66-interpret-failure-stage"), "interpreter_exception");
  assert.equal(upstreamFailure.headers.get("x-b66-interpret-exception-family"), "type_error");
  assert.equal(upstreamFailure.headers.get("x-internal-debug"), null);
  assert.equal(calls.length, 7);
  assert.equal(calls[6].url, "https://chat.padiem.net/api/b66/quote/interpret");

  const countBeforeDeny = calls.length;
  for (const request of [
    new Request("https://quick-quote-kr.pages.dev/api/padiem/admin/anything"),
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/saved-skills/not-an-id"),
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/assets/not-an-id"),
    new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/pdf"),
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/status", { method: "POST" })
  ]) {
    const denied = await worker.fetch(request, env);
    assert.equal(denied.status, 404);
  }
  assert.equal(calls.length, countBeforeDeny);

  const googleStart = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/google/start"),
    env
  );
  assert.equal(googleStart.status, 302);
  assert.equal(googleStart.headers.get("location"), "https://accounts.google.com/o/oauth2/auth?provider=google");

  const googleCallback = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/google/callback?code=x&state=y"),
    env
  );
  assert.equal(googleCallback.status, 302);
  assert.equal(googleCallback.headers.get("location"), "/");

  let serviceCalls = 0;
  const serviceEnv = {
    ASSETS: assets,
    PADIEM_CHAT_SERVICE: {
      async fetch(request) {
        serviceCalls += 1;
        assert.equal(request.url, "https://chat.padiem.net/api/auth/status");
        assert.equal(request.headers.get("cookie"), "padiem_session=service-token");
        return json({
          authenticated: true,
          session_state: "signed_in",
          user: { id: "usr_service" }
        });
      }
    }
  };
  const networkCallsBeforeService = calls.length;
  const viaService = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/status", {
      headers: { "Cookie": "padiem_session=service-token" }
    }),
    serviceEnv
  );
  assert.equal(viaService.status, 200);
  assert.equal(serviceCalls, 1);
  assert.equal(calls.length, networkCallsBeforeService);

  const oversized = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/password/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": String(33 * 1024)
      },
      body: JSON.stringify({ identifier: "x", password: "y" })
    }),
    env
  );
  assert.equal(oversized.status, 413);

  const pdf = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Cookie": "padiem_session=pdf-test", "Origin": "https://quick-quote-kr.pages.dev", "Authorization": "Bearer forged" },
    body: JSON.stringify({ saved_skill_id: "b66skill_" + "c".repeat(32), render_model: { derivedBy: "quote-core" } })
  }), env);
  assert.equal(pdf.status, 200);
  assert.equal(pdf.headers.get("content-type"), "application/pdf");
  assert.equal(pdf.headers.get("content-disposition"), 'attachment; filename="quote-test.pdf"');
  assert.match(pdf.headers.get("cache-control"), /no-store/);
  assert.equal(pdf.headers.get("x-internal-debug"), null);
  assert.match(await pdf.text(), /^%PDF-/);
  assert.equal(calls.at(-1).url, "https://chat.padiem.net/api/b66/quote/pdf");
  assert.equal(calls.at(-1).headers.get("cookie"), "padiem_session=pdf-test");
  assert.equal(calls.at(-1).headers.get("authorization"), null);
  assert.equal(calls.at(-1).headers.get("accept"), "application/pdf,application/json");
  assert.equal(calls.at(-1).headers.get("origin"), "https://chat.padiem.net");
  const pdfCalls = calls.length;
  const beforeOriginDeny = calls.length;
  for (const originHeaders of [
    { "Content-Type": "application/json", "Cookie": "padiem_session=origin-test", "Origin": "https://evil.example" },
    { "Content-Type": "application/json", "Cookie": "padiem_session=origin-test" }
  ]) {
    const deniedOrigin = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/pdf", {
      method: "POST",
      headers: originHeaders,
      body: JSON.stringify({ saved_skill_id: "b66skill_" + "c".repeat(32), render_model: { derivedBy: "quote-core" } })
    }), env);
    assert.equal(deniedOrigin.status, 403);
    assert.equal((await deniedOrigin.json()).error.code, "padiem_origin_rejected");
  }
  assert.equal(calls.length, beforeOriginDeny);

  const oversizedPdf = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/pdf", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "x".repeat(33 * 1024)
  }), env);
  assert.equal(oversizedPdf.status, 413);
  assert.equal(calls.length, pdfCalls);

  for (const failure of [
    { status: 429, code: "rate_limited", headers: { "Retry-After": "60" } },
    { status: 503, code: "quote_model_unavailable", headers: {
      "X-B66-Model-Selection-Status": "ambiguous", "X-B66-Interpret-Failure-Stage": "model_selection"
    } }
  ]) {
    const boundaryEnv = { ...env, PADIEM_CHAT_SERVICE: { fetch: async () => json({ ok: false, error: { code: failure.code } }, {
      status: failure.status, headers: { ...failure.headers, "X-Internal-Debug": "must-not-relay" }
    }) } };
    const forwarded = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret", {
      method: "POST", headers: { "Content-Type": "application/json", "Cookie": "padiem_session=boundary-test", "Origin": "https://quick-quote-kr.pages.dev" },
      body: JSON.stringify({ saved_skill_id: "b66skill_" + "c".repeat(32), message: "synthetic" })
    }), boundaryEnv);
    assert.equal(forwarded.status, failure.status);
    for (const [name, value] of Object.entries(failure.headers)) assert.equal(forwarded.headers.get(name), value);
    assert.match(forwarded.headers.get("cache-control"), /no-store/);
    assert.equal(forwarded.headers.get("X-Internal-Debug"), null);
  }
  for (const [sourceOrigin, expected] of [
    ["registered_model_completion", "registered_model_completion"],
    ["deterministic_fallback", "deterministic_fallback"],
    ["forged-raw-secret", null]
  ]) {
    const originEnv = {
      ...env,
      PADIEM_CHAT_SERVICE: {
        fetch: async () => json(
          { ok: true, candidate: { items: [{ name: "Synthetic Item" }] } },
          { status: 200, headers: {
            "X-B66-Result-Origin": sourceOrigin,
            "X-Internal-Debug": "must-not-relay"
          } }
        )
      }
    };
    const forwarded = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Cookie": "padiem_session=synthetic", "Origin": "https://quick-quote-kr.pages.dev" },
      body: JSON.stringify({ saved_skill_id: "b66skill_" + "c".repeat(32), model_id: "google/gemini-3.5-flash-lite", message: "synthetic" })
    }), originEnv);
    assert.equal(forwarded.status, 200);
    assert.equal(forwarded.headers.get("x-b66-result-origin"), expected);
    assert.equal(forwarded.headers.get("x-internal-debug"), null);
    assert.match(forwarded.headers.get("cache-control"), /no-store/);
    assert.equal((await forwarded.json()).candidate.items[0].name, "Synthetic Item");
  }
  console.log("B66_RESULT_ORIGIN_HEADER_RELAY=PASS");
  console.log("B66_QUOTA_AND_SELECTION_DIAGNOSTIC_RELAY=PASS");
  console.log("PADIEM_ACCOUNT_BRIDGE_RUNTIME=PASS");
  console.log("ARBITRARY_UPSTREAM_PROXY=0");
  console.log("AUTHORIZATION_HEADER_FORWARD=0");
  console.log("OPAQUE_SESSION_COOKIE_RELAY=PASS");
  console.log("PRIVATE_QUOTE_ASSET_PROXY=PASS");
  console.log("CERTIFIED_QUOTE_PDF_PROXY=PASS");
  console.log("B66_REJECTION_DIAGNOSTIC_HEADER_RELAY=PASS");
  console.log("B66_UPSTREAM_CLASS_DIAGNOSTIC_HEADER_RELAY=PASS");
  console.log("ARBITRARY_RESPONSE_HEADER_RELAY=0");
  console.log("SERVICE_BINDING_PRIORITY=PASS");
  console.log("PRODUCTION_MUTATION=0");
} finally {
  globalThis.fetch = originalFetch;
}
