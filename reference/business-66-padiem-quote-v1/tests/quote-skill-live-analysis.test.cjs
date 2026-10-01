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

  /* Native documents are parsed locally first; raw document bytes are not posted. */
  const documentBytes = Uint8Array.from([80, 75, 3, 4, 1, 2, 3, 4]);
  const documentFile = {
    arrayBuffer: async () => documentBytes.buffer.slice(
      documentBytes.byteOffset,
      documentBytes.byteOffset + documentBytes.byteLength
    )
  };
  const documentMeta = {
    name: "quotation.docx",
    extension: ".docx",
    mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    byteSize: documentBytes.byteLength,
    category: "native_document"
  };
  const documentCalls = [];
  const documentExtraction = {
    source: { kind: "native_document", filename: "quotation.docx" },
    sender: { company: "문서 테스트상사" },
    recipient: { company: "문서 거래처" },
    quote: { quoteNo: "DOCX-Q-1" },
    items: [{ name: "문서 품목", qty: 2, unitPrice: 5000 }],
    tax: { mode: "EXCLUSIVE" },
    memo: null,
    evidence: [],
    warnings: []
  };
  const localParser = async () => ({
    ok: true,
    kind: "local_text",
    text: "견적번호 DOCX-Q-1\n문서 품목 2 5000",
    textChars: 26,
    byteSize: documentBytes.byteLength,
    parser: "test-local"
  });

  const documentResult = await SkillUi.analyzeFile(
    documentFile,
    documentMeta,
    async (url, options) => {
      documentCalls.push({ url, options });
      return {
        ok: true,
        json: async () => ({
          ok: true,
          result: { extraction: documentExtraction, unknowns: ["quote.issueDate"] }
        })
      };
    },
    localParser
  );
  assert.equal(documentResult.ok, true);
  assert.deepEqual(documentResult.extraction, documentExtraction);
  assert.deepEqual(documentResult.unknowns, ["quote.issueDate"]);
  assert.equal(documentCalls.length, 1);
  assert.equal(documentCalls[0].url, "/api/v1/quote/intake");

  const documentPosted = JSON.parse(documentCalls[0].options.body);
  assert.deepEqual(documentPosted, {
    name: "quotation.docx",
    media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    byte_size: documentBytes.byteLength,
    local_text: "견적번호 DOCX-Q-1\n문서 품목 2 5000"
  });
  assert.ok(!("base64" in documentPosted));
  assert.ok(!("model" in documentPosted) && !("provider" in documentPosted) && !("secret" in documentPosted));

  let fetchCallsAfterLocalFailure = 0;
  const localFailure = await SkillUi.analyzeFile(
    documentFile,
    documentMeta,
    async () => {
      fetchCallsAfterLocalFailure += 1;
      throw new Error("must not post when local parsing fails");
    },
    async () => ({ ok: false, code: "zip_path_traversal" })
  );
  assert.deepEqual(localFailure, { ok: false, code: "zip_path_traversal" });
  assert.equal(fetchCallsAfterLocalFailure, 0);

  console.log("quote-skill live image/native analysis contracts: PASS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
