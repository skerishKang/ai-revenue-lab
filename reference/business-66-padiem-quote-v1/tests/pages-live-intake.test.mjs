import assert from "node:assert/strict";
import fs from "node:fs";
import worker from "../_worker.js";

/* #3481 Policy A: standalone /api/v1/quote/intake 는 fail-closed 로 비활성화되어야 한다.
   이 테스트의 목적은 요청 모양별 parsing contract 가 아니라
   "provider forwarding 이 원천적으로 불가능"함을 증명하는 것이다. */

const originalFetch = globalThis.fetch;
const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
};

try {
  const env = {
    ASSETS: {
      fetch() {
        throw new Error("assets must not handle API");
      }
    }
  };

  const intakeUrl = "https://quick-quote-kr.pages.dev/api/v1/quote/intake";
  const post = (body, contentType = "application/json") =>
    worker.fetch(new Request(intakeUrl, { method: "POST", headers: { "Content-Type": contentType }, body }), env);

  const disabledPayload = async (response, label) => {
    assert.equal(response.status, 410, label + ": disabled status");
    const payload = await response.json();
    assert.equal(payload.ok, false, label + ": ok=false envelope");
    assert.equal(payload.error && payload.error.code, "intake_disabled", label + ": bounded code only");
    assert.equal(response.headers.get("Cache-Control"), "no-store", label + ": no-store");
    const bodyText = JSON.stringify(payload);
    assert.ok(!bodyText.includes("extract-"), label + ": no provider endpoint leak");
    assert.ok(!bodyText.includes("workers.dev"), label + ": no provider host leak");
    assert.ok(!bodyText.includes("b66/v1"), label + ": no provider path leak");
    return payload;
  };

  /* image request -> disabled response, provider call 0 */
  const imageResponse = await post(JSON.stringify({ name: "q.png", media_type: "image/png", base64: "AA==" }));
  await disabledPayload(imageResponse, "image");
  assert.equal(calls.length, 0, "image: no fetch while disabled");

  /* document request -> disabled response, provider call 0 */
  const documentResponse = await post(JSON.stringify({ name: "q.pdf", media_type: "application/pdf", base64: "JVBERi0=" }));
  await disabledPayload(documentResponse, "document");
  assert.equal(calls.length, 0, "document: no fetch while disabled");

  /* malformed request -> provider call 0, same bounded disabled contract */
  const malformed = await post("{");
  await disabledPayload(malformed, "malformed");
  assert.equal(calls.length, 0, "malformed: no fetch while disabled");

  /* oversized body / non-JSON content-type 도 route 가 닫혀 있으므로 동일하게 귀결된다 */
  const oversized = await post(JSON.stringify({ name: "big.png", media_type: "image/png", base64: "A".repeat(8 * 1024 * 1024) }));
  await disabledPayload(oversized, "oversized");
  const wrongType = await post("{}", "text/plain");
  await disabledPayload(wrongType, "wrong-content-type");
  const nonPost = await worker.fetch(new Request(intakeUrl, { method: "GET" }), env);
  await disabledPayload(nonPost, "GET");
  assert.equal(calls.length, 0, "every request shape: provider forwarding stays at 0");

  /* padiem auth/session bridge 는 그대로 정상이어야 한다 (routing smoke) */
  const statusResponse = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/status", { method: "GET" }), env);
  assert.equal(statusResponse.status, 200);
  assert.match(calls[calls.length - 1].url, /^https:\/\/chat\.padiem\.net\/api\/auth\/status$/);
  const loginResponse = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/padiem/auth/password/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: "probe", password: "probe" })
    }), env);
  assert.equal(loginResponse.status, 200);
  assert.match(calls[calls.length - 1].url, /^https:\/\/chat\.padiem\.net\/api\/auth\/password\/login$/);

  /* asset fallback 은 그대로 */
  const assetResponse = new Response("asset", { status: 200 });
  let assetCalls = 0;
  const assetEnv = { ASSETS: { fetch() { assetCalls += 1; return assetResponse; } } };
  const asset = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/app.js"), assetEnv);
  assert.equal(asset.status, 200);
  assert.equal(assetCalls, 1);

  /* source contract: provider relay code 가 남아 있지 않다 */
  const source = fs.readFileSync(new URL("../_worker.js", import.meta.url), "utf8");
  assert.ok(!source.includes("B14_IMAGE_EXTRACTION_URL"), "no image provider URL constant");
  assert.ok(!source.includes("B14_DOCUMENT_EXTRACTION_URL"), "no document provider URL constant");
  assert.ok(!source.includes("extract-image"), "no extract-image endpoint");
  assert.ok(!source.includes("extract-document"), "no extract-document endpoint");
  assert.ok(!source.includes("upstreamForBody"), "no provider routing helper");
  assert.ok(!source.includes("MAX_RESPONSE_BYTES"), "no provider response limit remains");
  assert.ok(!/space-bunny|sensenova|openai|anthropic|kilo\//i.test(source));
  assert.ok(!/api[_-]?key|secret/i.test(source));
  assert.ok(!/\\bpassword\\s*[:=]/i.test(source));

  /* primary CGI Home flow 소스는 intake endpoint 를 전혀 참조하지 않는다 */
  const readSource = (file) => fs.readFileSync(new URL("../" + file, import.meta.url), "utf8");
  const primaryFlowSources = ["easy-mode.js", "app.js", "file-intake.js", "quote-core.js"].map(readSource);
  assert.ok(primaryFlowSources.every((text) => !text.includes("quote/intake")),
    "primary CGI flow does not call the intake endpoint");

  console.log("INTAKE_ROUTE_DISABLED=PASS");
  console.log("PUBLIC_UNAUTHENTICATED_EXTRACTION_RELAY=0");
  console.log("PROVIDER_FORWARD_CALLS=0");
  console.log("B14_IMAGE_FORWARD_CALLS=0");
  console.log("B14_DOCUMENT_FORWARD_CALLS=0");
  console.log("PRIMARY_CGI_FLOW_DEPENDS_ON_INTAKE=NO");
  console.log("b66 Pages intake relay disabled contracts: PASS");
} finally {
  globalThis.fetch = originalFetch;
}
