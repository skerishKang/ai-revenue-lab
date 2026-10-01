import assert from "node:assert/strict";
import worker from "../_worker.js";

const originalFetch = globalThis.fetch;
const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  const target = String(url);
  const isDocument = target.endsWith("/api/b66/v1/quote/extract-document");
  const isLocalText = target.endsWith("/api/b66/v1/quote/extract-local-text");
  return new Response(
    JSON.stringify({
      ok: true,
      result: {
        extraction: {
          source: {
            kind: (isDocument || isLocalText) ? "native_document" : "image",
            filename: isLocalText ? "q.docx" : (isDocument ? "q.pdf" : "q.png")
          },
          sender: {}, recipient: {}, quote: {}, items: [], tax: { mode: null },
          memo: null, evidence: [], warnings: []
        },
        unknowns: []
      }
    }),
    { status: 200, headers: { "Content-Type": "application/json" } }
  );
};

try {
  const env = {
    ASSETS: {
      fetch() {
        throw new Error("assets must not handle API");
      }
    }
  };

  const imageRequest = new Request("https://quick-quote-kr.pages.dev/api/v1/quote/intake", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "q.png", media_type: "image/png", base64: "AA==" })
  });
  const imageResponse = await worker.fetch(imageRequest, env);
  assert.equal(imageResponse.status, 200);
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/api\/b66\/v1\/quote\/extract-image$/);
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(imageResponse.headers.get("Cache-Control"), "no-store");

  const documentRequest = new Request("https://quick-quote-kr.pages.dev/api/v1/quote/intake", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: "q.pdf",
      media_type: "application/pdf",
      base64: "JVBERi0="
    })
  });
  const documentResponse = await worker.fetch(documentRequest, env);
  assert.equal(documentResponse.status, 200);
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /\/api\/b66\/v1\/quote\/extract-document$/);
  assert.equal(calls[1].options.method, "POST");
  assert.equal(calls[1].options.headers["Content-Type"], "application/json");
  assert.equal(documentResponse.headers.get("Cache-Control"), "no-store");

  const localTextRequest = new Request("https://quick-quote-kr.pages.dev/api/v1/quote/intake", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: "q.docx",
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      byte_size: 1234,
      local_text: "견적번호 Q-LOCAL-1\n품목 테스트 2 3000"
    })
  });
  const localTextResponse = await worker.fetch(localTextRequest, env);
  assert.equal(localTextResponse.status, 200);
  assert.equal(calls.length, 3);
  assert.match(calls[2].url, /\/api\/b66\/v1\/quote\/extract-local-text$/);
  assert.equal(calls[2].options.method, "POST");
  assert.equal(calls[2].options.headers["Content-Type"], "application/json");
  assert.equal(localTextResponse.headers.get("Cache-Control"), "no-store");
  const forwardedLocal = JSON.parse(new TextDecoder().decode(calls[2].options.body));
  assert.equal(forwardedLocal.local_text, "견적번호 Q-LOCAL-1\n품목 테스트 2 3000");
  assert.ok(!("base64" in forwardedLocal));

  const malformed = await worker.fetch(
    new Request("https://quick-quote-kr.pages.dev/api/v1/quote/intake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{"
    }),
    env
  );
  assert.equal(malformed.status, 422);
  assert.equal(calls.length, 3);

  const assetResponse = new Response("asset", { status: 200 });
  let assetCalls = 0;
  const assetEnv = { ASSETS: { fetch() { assetCalls += 1; return assetResponse; } } };
  const asset = await worker.fetch(new Request("https://quick-quote-kr.pages.dev/app.js"), assetEnv);
  assert.equal(asset.status, 200);
  assert.equal(assetCalls, 1);

  const source = await import("node:fs").then((fs) =>
    fs.readFileSync(new URL("../_worker.js", import.meta.url), "utf8")
  );
  assert.ok(!/space-bunny|sensenova|openai|anthropic|kilo\//i.test(source));
  assert.ok(!/api[_-]?key|password|secret/i.test(source));
  console.log("b66 Pages image/binary/local-text intake proxy contracts: PASS");
} finally {
  globalThis.fetch = originalFetch;
}
