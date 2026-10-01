const assert = require("node:assert/strict");
const SkillUi = require("../quote-skill-ui.js");

async function main() {
  const imageBytes = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3, 4]);
  const imageFile = {
    arrayBuffer: async () => imageBytes.buffer.slice(
      imageBytes.byteOffset,
      imageBytes.byteOffset + imageBytes.byteLength
    )
  };
  const imageMeta = {
    name: "quotation.png",
    mediaType: "image/png",
    byteSize: imageBytes.byteLength,
    category: "image"
  };
  const imageCalls = [];
  const imageExtraction = {
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

  const imageResult = await SkillUi.analyzeImageFile(imageFile, imageMeta, async (url, options) => {
    imageCalls.push({ url, options });
    return {
      ok: true,
      json: async () => ({ ok: true, result: { extraction: imageExtraction, unknowns: ["memo"] } })
    };
  });

  assert.equal(imageResult.ok, true);
  assert.deepEqual(imageResult.extraction, imageExtraction);
  assert.deepEqual(imageResult.unknowns, ["memo"]);
  assert.equal(imageCalls.length, 1);
  assert.equal(imageCalls[0].url, "/api/v1/quote/intake");
  assert.equal(imageCalls[0].options.method, "POST");
  assert.equal(imageCalls[0].options.headers["Content-Type"], "application/json");

  const imagePosted = JSON.parse(imageCalls[0].options.body);
  assert.equal(imagePosted.name, "quotation.png");
  assert.equal(imagePosted.media_type, "image/png");
  assert.equal(Buffer.from(imagePosted.base64, "base64").length, imageBytes.byteLength);
  assert.ok(!("model" in imagePosted) && !("provider" in imagePosted) && !("secret" in imagePosted));

  const imageFailed = await SkillUi.analyzeImageFile(imageFile, imageMeta, async () => ({
    ok: false,
    json: async () => ({ ok: false, error: { code: "b14_upstream_unavailable" } })
  }));
  assert.deepEqual(imageFailed, { ok: false, code: "b14_upstream_unavailable" });

  /* Backward-compatible image-only helper still refuses native documents. */
  const manual = await SkillUi.analyzeImageFile(
    imageFile,
    { ...imageMeta, category: "native_document" },
    async () => { throw new Error("must not call"); }
  );
  assert.deepEqual(manual, { ok: false, code: "manual_only" });

  /* New generic analysis helper sends native documents through the same-origin route. */
  const pdfBytes = Uint8Array.from([37, 80, 68, 70, 45, 49, 46, 55, 10, 37, 37, 69, 79, 70]);
  const pdfFile = {
    arrayBuffer: async () => pdfBytes.buffer.slice(
      pdfBytes.byteOffset,
      pdfBytes.byteOffset + pdfBytes.byteLength
    )
  };
  const pdfMeta = {
    name: "quotation.pdf",
    mediaType: "application/pdf",
    byteSize: pdfBytes.byteLength,
    category: "native_document"
  };
  const documentCalls = [];
  const documentExtraction = {
    source: { kind: "native_document", filename: "quotation.pdf" },
    sender: { company: "문서 테스트상사" },
    recipient: { company: "문서 거래처" },
    quote: { quoteNo: "PDF-Q-1" },
    items: [{ name: "문서 품목", qty: 2, unitPrice: 5000 }],
    tax: { mode: "EXCLUSIVE" },
    memo: null,
    evidence: [],
    warnings: []
  };

  const documentResult = await SkillUi.analyzeFile(pdfFile, pdfMeta, async (url, options) => {
    documentCalls.push({ url, options });
    return {
      ok: true,
      json: async () => ({
        ok: true,
        result: { extraction: documentExtraction, unknowns: ["quote.issueDate"] }
      })
    };
  });
  assert.equal(documentResult.ok, true);
  assert.deepEqual(documentResult.extraction, documentExtraction);
  assert.deepEqual(documentResult.unknowns, ["quote.issueDate"]);
  assert.equal(documentCalls.length, 1);
  assert.equal(documentCalls[0].url, "/api/v1/quote/intake");
  const documentPosted = JSON.parse(documentCalls[0].options.body);
  assert.equal(documentPosted.name, "quotation.pdf");
  assert.equal(documentPosted.media_type, "application/pdf");
  assert.equal(Buffer.from(documentPosted.base64, "base64").length, pdfBytes.byteLength);
  assert.ok(!("model" in documentPosted) && !("provider" in documentPosted) && !("secret" in documentPosted));

  const parserUnavailable = await SkillUi.analyzeFile(pdfFile, pdfMeta, async () => ({
    ok: false,
    json: async () => ({ ok: false, error: { code: "parser_authority_unavailable" } })
  }));
  assert.deepEqual(parserUnavailable, { ok: false, code: "parser_authority_unavailable" });

  console.log("quote-skill live image/native analysis contracts: PASS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
