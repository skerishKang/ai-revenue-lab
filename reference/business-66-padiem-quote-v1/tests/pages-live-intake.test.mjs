import assert from "node:assert/strict";
import worker from "../_worker.js";

const originalFetch = globalThis.fetch;
const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  return new Response(
    JSON.stringify({
      ok: true,
      result: {
        extraction: {
          source: { kind: "image", filename: "q.png" },
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
  const request = new Request("https://quick-quote-kr.pages.dev/api/v1/quote/intake", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "q.png", media_type: "image/png", base64: "AA==" })
  });
  const env = {
    ASSETS: {
      fetch() {
        throw new Error("assets must not handle API");
      }
    }
  };
  const response = await worker.fetch(request, env);
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/api\/b66\/v1\/quote\/extract-image$/);
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(response.headers.get("Cache-Control"), "no-store");

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
  console.log("b66 Pages live-intake proxy contracts: PASS");
} finally {
  globalThis.fetch = originalFetch;
}
