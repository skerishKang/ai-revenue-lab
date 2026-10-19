/* B66 #5094 — the file-analysis 410 stays a truthful, closed outcome.

   The production bridge answers ``POST /api/v1/quote/intake`` with
   ``410 intake_disabled`` by policy (no standalone extraction provider). The
   client must surface that as "cannot analyze now", never as success, and must
   offer manual entry without retrying through another endpoint. */

const assert = require("node:assert");
const Ui = require("../quote-skill-ui.js");
const Auto = require("../quote-skill-auto.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const FILE_META = {
  name: "old-quote.pdf",
  category: "native_document",
  mediaType: "application/pdf",
  byteSize: 4
};

function file() {
  return {
    arrayBuffer: () => Promise.resolve(new Uint8Array([0x25, 0x50, 0x44, 0x46]).buffer)
  };
}

function disabledResponse() {
  return {
    ok: false,
    status: 410,
    json: async () => ({ ok: false, error: { code: "intake_disabled" } })
  };
}

(async () => {
  const calls = [];
  const result = await Ui.analyzeFile(file(), FILE_META, async (url, init) => {
    calls.push({ url, init });
    return disabledResponse();
  });

  eq(result, { ok: false, code: "intake_disabled" }, "410 intake_disabled is preserved as a failure code");
  check(calls.length === 1, "the client sends exactly one intake request and never retries");
  check(calls[0].url === "/api/v1/quote/intake", "the existing same-origin seam is used");
  check(calls[0].init && calls[0].init.method === "POST", "intake remains a single bounded POST");

  /* A closed 410 with a non-JSON body must still fail closed, not throw through. */
  const opaque = await Ui.analyzeFile(file(), FILE_META, async () => ({
    ok: false,
    status: 410,
    json: async () => { throw new SyntaxError("not json"); }
  }));
  eq(opaque, { ok: false, code: "analysis_service_unavailable" }, "opaque 410 degrades to an unavailable analysis");

  /* The UI message must send the owner to manual entry and never claim analysis. */
  const message = Auto.analysisFailureMessage("intake_disabled");
  eq(message, Auto.ANALYSIS_UNAVAILABLE, "intake_disabled uses the unavailable-analysis message");
  check(message.includes("직접") && message.includes("승인 요청"), "the message explains the manual path");
  check(!message.includes("완료") && !message.includes("성공"), "the message never presents the closed path as success");
  check(Auto.FILE_ERRORS.intake_disabled === Auto.ANALYSIS_UNAVAILABLE, "the code map and the message agree");

  /* No alternate extraction endpoint may be introduced as a bypass. */
  const source = require("node:fs").readFileSync(
    require("node:path").join(__dirname, "..", "quote-skill-ui.js"), "utf8"
  );
  const endpoints = source.match(/"\/api\/v1\/quote\/intake"/g) || [];
  check(endpoints.length === 1, "the UI declares the intake endpoint once");

  console.log("B66_INTAKE_410_CODES_PRESERVED=YES");
  console.log("B66_INTAKE_410_RETRY_OR_BYPASS=0");
})().catch((error) => {
  console.error("B66_INTAKE_410_5094=FAIL");
  console.error(error && error.message ? error.message : error);
  process.exitCode = 1;
});
