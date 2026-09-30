const assert = require("node:assert/strict");
const SkillUi = require("../quote-skill-ui.js");

async function main() {
  const bytes = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3, 4]);
  const file = {
    arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
  };
  const meta = {
    name: "quotation.png",
    mediaType: "image/png",
    byteSize: bytes.byteLength,
    category: "image"
  };
  const calls = [];
  const extraction = {
    source: { kind: "image", filename: "quotation.png" },
    sender: { company: "테스트상사" },
    recipient: { company: "원본거래처" },
    quote: { quoteNo: "Q-1" },
    items: [{ name: "품목", qty: 1, unitPrice: 1000 }],
    tax: { mode: "EXCLUSIVE" },
    memo: null,
    evidence: [],
    warnings: []
  };

  const result = await SkillUi.analyzeImageFile(file, meta, async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({ ok: true, result: { extraction, unknowns: ["memo"] } })
    };
  });

  assert.equal(result.ok, true);
  assert.deepEqual(result.extraction, extraction);
  assert.deepEqual(result.unknowns, ["memo"]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/v1/quote/intake");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");

  const posted = JSON.parse(calls[0].options.body);
  assert.equal(posted.name, "quotation.png");
  assert.equal(posted.media_type, "image/png");
  assert.equal(Buffer.from(posted.base64, "base64").length, bytes.byteLength);
  assert.ok(!("model" in posted) && !("provider" in posted) && !("secret" in posted));

  const failed = await SkillUi.analyzeImageFile(file, meta, async () => ({
    ok: false,
    json: async () => ({ ok: false, error: { code: "b14_upstream_unavailable" } })
  }));
  assert.deepEqual(failed, { ok: false, code: "b14_upstream_unavailable" });

  const manual = await SkillUi.analyzeImageFile(
    file,
    { ...meta, category: "native_document" },
    async () => { throw new Error("must not call"); }
  );
  assert.deepEqual(manual, { ok: false, code: "manual_only" });

  console.log("quote-skill live image analysis contracts: PASS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
