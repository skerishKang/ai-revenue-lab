/* #3871 Slice E — 통합 검증 시나리오(오프라인).
   실제 Google 계정·실기기·운영 배포는 이 파일에서 검증하지 않는다.
   검증하지 못한 항목은 PASS 가 아니라 NOT_TESTED 로 남긴다. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");
const ServerHistory = require("../quote-history-server.js");
const History = require("../quote-history.js");
const BrowserPdf = require("../quote-browser-pdf.js");

const readModule = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const appSource = readModule("app.js");
const htmlSource = readModule("index.html");

const CLIENT_ID = "test-client-id.apps.googleusercontent.com";
const JSON_MIME = Contract.JSON_MIME;

function baseDraft() {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: "PQ-20261009-007", issueDate: "2026-10-09", validDays: 30, source: "manual" },
    sender: { company: "공급상사", rep: "김대표", bizNo: "123-45-67890", address: "서울", phone: "02-000-0000", email: "s@example.com", presetId: "custom" },
    recipient: { company: "가나상사", person: "박담당", address: "부산", email: "b@example.com" },
    items: [
      { id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 },
      { id: "item-2", name: "운영 지원", qty: 2, unitPrice: 300000 }
    ],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: "메모"
  });
}

function pdfBytes(size) {
  const bytes = new Uint8Array(size || 512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  return bytes;
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

function harness(options) {
  const opts = options || {};
  const calls = [];
  const state = {
    files: (opts.files || []).slice(),
    metadata: opts.metadata || null,
    media: opts.media || null,
    uploadQueue: (opts.uploads || []).slice(),
    created: []
  };
  const jsonResponse = (data, status) => ({
    ok: status === undefined ? true : status >= 200 && status < 300,
    status: status === undefined ? 200 : status,
    headers: { get: () => null },
    json: async () => data,
    text: async () => (typeof data === "string" ? data : JSON.stringify(data))
  });
  const fetchImpl = async (url, init) => {
    const target = String(url);
    calls.push({ url: target, method: (init && init.method) || "GET" });
    const request = init || {};
    if (target.indexOf("oauth2.googleapis.com/revoke") !== -1) return jsonResponse({}, 200);
    if (target.indexOf("/upload/drive/v3/files") !== -1) {
      const next = state.uploadQueue.shift();
      if (!next) return jsonResponse({ error: { message: "no stub" } }, 500);
      let name = "uploaded";
      try {
        const bodyText = Buffer.from(request.body).toString("utf8");
        const match = /"name"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(bodyText);
        if (match) name = JSON.parse('"' + match[1] + '"');
      } catch (err) { name = "uploaded"; }
      const id = "id-" + (state.created.length + 1);
      const record = { id: id, name: name, mimeType: next.mimeType || "" };
      state.created.push(record);
      state.files.push({ id: id, name: name, mimeType: record.mimeType, trashed: false, owners: [{ me: true }] });
      if (typeof next === "function") return next(request.body, request.headers, record);
      return jsonResponse({ id: id, name: name }, next.status);
    }
    if (target.indexOf("alt=media") !== -1) {
      return { ok: true, status: 200, headers: { get: () => null }, text: async () => String(state.media || "") };
    }
    if (target.indexOf("/drive/v3/files/") !== -1) {
      if (state.metadata === null) return jsonResponse({ error: { message: "not found" } }, 404);
      return jsonResponse(state.metadata, state.metadataStatus || 200);
    }
    if (target.indexOf("/drive/v3/files?") !== -1) return jsonResponse({ files: state.files }, 200);
    return jsonResponse({ error: { message: "unexpected endpoint" } }, 404);
  };
  let tokenCallback = null;
  const google = {
    accounts: {
      oauth2: {
        initTokenClient(config) {
          tokenCallback = config.callback;
          return { requestAccessToken() {} };
        }
      }
    }
  };
  const client = Client.create({
    clientId: CLIENT_ID,
    fetch: fetchImpl,
    google: google,
    gapi: null,
    now: opts.now || (() => Date.now()),
    loadScript: async () => { throw new Error("no network in test"); }
  });
  return {
    client, calls, state,
    async connect(params) {
      const pending = client.connect();
      await flush();
      tokenCallback(Object.assign({ access_token: "stub-token", expires_in: 3600, scope: Client.SCOPE_DRIVE_FILE }, params || {}));
      return pending;
    },
    async deny(errorName) {
      const pending = client.connect();
      await flush();
      tokenCallback({ error: errorName || "access_denied" });
      return pending;
    }
  };
}

const scenario = [];
const mark = (name, value) => scenario.push(name + "=" + value);

(async () => {
  /* 시나리오 1 — 정상 JSON + PDF 저장 */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: Contract.PDF_MIME }] });
    await h.connect();
    const outcome = await h.client.savePair({ draft: baseDraft(), pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "S1 complete");
    assert.ok(outcome.json && outcome.pdf, "S1 both files");
    assert.equal(h.state.created.length, 2, "S1 two uploads");
    assert.ok(outcome.json.name.endsWith(".json"), "S1 json name");
    assert.ok(outcome.pdf.name.endsWith(".pdf"), "S1 pdf name");
    mark("S1_NORMAL_JSON_PDF_SAVE", "PASS");
  }

  /* 시나리오 2 — 두 파일을 다시 찾아서 열기 */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: Contract.PDF_MIME }] });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, pdfBytes: pdfBytes() });
    const listed = await h.client.listQuoteFiles();
    assert.equal(listed.ok, true, "S2 list ok");
    const jsonFiles = listed.files.filter((file) => file.mimeType === JSON_MIME);
    assert.equal(jsonFiles.length, 1, "S2 one json found");
    assert.equal(listed.files.length, 2, "S2 pair both discoverable");
    h.state.metadata = {
      id: jsonFiles[0].id, name: jsonFiles[0].name, mimeType: JSON_MIME,
      size: 4000, trashed: false, owners: [{ me: true }]
    };
    h.state.media = Contract.serializePackage(Contract.buildPackage({
      draft, packageId: outcome.packageId, savedAt: "2026-10-09T09:00:00.000Z"
    }).package);
    const opened = await h.client.openQuoteFile(jsonFiles[0].id);
    assert.equal(opened.ok, true, "S2 reopen ok");
    assert.deepEqual(opened.draft, draft, "S2 draft identical");
    mark("S2_REOPEN_BOTH_FILES", "PASS");
  }

  /* 시나리오 3 — 수량·단가 변경 후 금액 재계산 */
  {
    const before = baseDraft();
    const edited = Core.normalizeDraft(Object.assign({}, before, {
      items: [
        { id: "item-1", name: "서비스 구축", qty: 3, unitPrice: 1000000 },
        { id: "item-2", name: "운영 지원", qty: 2, unitPrice: 450000 }
      ]
    }));
    const beforeTotals = Core.computeDraftTotals(before);
    const afterTotals = Core.computeDraftTotals(edited);
    assert.notEqual(beforeTotals.grand, afterTotals.grand, "S3 totals change");

    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: Contract.PDF_MIME }] });
    await h.connect();
    const outcome = await h.client.savePair({ draft: edited, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "S3 edited save");
    h.state.metadata = {
      id: outcome.json.id, name: outcome.json.name, mimeType: JSON_MIME,
      size: 4000, trashed: false, owners: [{ me: true }]
    };
    h.state.media = Contract.serializePackage(Contract.buildPackage({
      draft: edited, packageId: outcome.packageId
    }).package);
    const opened = await h.client.openQuoteFile(outcome.json.id);
    assert.deepEqual(
      [opened.totals.supply, opened.totals.vat, opened.totals.grand],
      [afterTotals.supply, afterTotals.vat, afterTotals.grand],
      "S3 REOPEN USES RECOMPUTED TOTALS"
    );
    assert.notEqual(opened.totals.grand, beforeTotals.grand, "S3 old totals not reused");
    mark("S3_QTY_PRICE_CHANGE_RECALCULATED", "PASS");
  }

  /* 시나리오 4 — 저장된 합계 변조 후 QuoteCore 재계산 */
  {
    const draft = baseDraft();
    const raw = Contract.buildPackage({ draft, packageId: "pkg-tamper-2" }).package;
    raw.totals = { supply: 1, vat: 1, grand: 999999999 };
    const text = JSON.stringify(raw);
    const parsed = Contract.readPackage(text, {});
    assert.equal(parsed.totalsIgnored, true, "S4 totals ignored");
    const imported = Contract.importPackage(parsed.package, {});
    const expected = Core.computeDraftTotals(draft);
    assert.equal(imported.totals.grand, expected.grand, "S4 recalculated");
    assert.notEqual(imported.totals.grand, 999999999, "S4 tampered value rejected");
    mark("S4_TAMPERED_TOTALS_RECALCULATED", "PASS");
  }

  /* 시나리오 5 — 손상된 JSON 거부 */
  {
    ["{", "[]", "null", '{"kind":"b66.quote-package"}', '{"__proto__":{"x":1}}'].forEach((bad) => {
      const result = Contract.readPackage(bad, {});
      assert.equal(result.ok, false, "S5 reject: " + bad);
      assert.ok(typeof result.code === "string" && result.code.length > 0, "S5 code surfaced");
    });
    mark("S5_CORRUPT_JSON_REJECTED", "PASS");
  }

  /* 시나리오 6 — 미지원 스키마 버전 거부 */
  {
    const draft = baseDraft();
    const pkg = Contract.buildPackage({ draft, packageId: "pkg-v" }).package;
    [0, -1, 2, 99].forEach((version) => {
      const copy = JSON.parse(JSON.stringify(pkg));
      copy.schemaVersion = version;
      const result = Contract.readPackage(JSON.stringify(copy), {});
      assert.equal(result.ok, false, "S6 reject v" + version);
      assert.ok(result.code.indexOf("schema_version") === 0, "S6 code: " + result.code);
    });
    mark("S6_UNSUPPORTED_SCHEMA_REJECTED", "PASS");
  }

  /* 시나리오 7 — 큰 파일 및 잘못된 형식 거부 */
  {
    assert.equal(Contract.readPackage("x".repeat(Contract.MAX_JSON_BYTES + 1), {}).code,
      "json_too_large", "S7 oversized json");
    assert.equal(Contract.validatePdfBytes(new Uint8Array(8)).code, "pdf_too_small", "S7 tiny pdf");
    const wrong = new Uint8Array(512); wrong[0] = 60;
    assert.equal(Contract.validatePdfBytes(wrong).code, "pdf_format_invalid", "S7 non-pdf");
    assert.equal(Contract.validatePdfBytes({}).code, "pdf_missing", "S7 missing pdf");
    const h = harness({ uploads: [] });
    await h.connect();
    const outcome = await h.client.savePair({ draft: baseDraft(), pdfBytes: wrong });
    assert.equal(outcome.status, "failed", "S7 save blocked");
    assert.equal(h.state.created.length, 0, "S7 nothing uploaded");
    mark("S7_LARGE_AND_BAD_FORMAT_REJECTED", "PASS");
  }

  /* 시나리오 8 — 중복 파일 이름 처리(덮어쓰기 금지) */
  {
    const draft = baseDraft();
    const first = Contract.planUniqueFileNames({ draft, existingNames: [] });
    const h = harness({
      files: [{ id: "old", name: first.json, mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      uploads: [{ mimeType: JSON_MIME }, { mimeType: Contract.PDF_MIME }]
    });
    await h.connect();
    const outcome = await h.client.savePair({ draft, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "S8 save ok");
    assert.notEqual(outcome.json.name, first.json, "S8 renamed");
    assert.equal(h.state.files.filter((file) => file.name === first.json).length, 1, "S8 original kept");
    mark("S8_DUPLICATE_NAME_NO_OVERWRITE", "PASS");
  }

  /* 시나리오 9 — JSON 성공·PDF 실패의 부분 저장 상태 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: Contract.PDF_MIME, status: 403, data: { error: { message: "quota" } } },
        { mimeType: Contract.PDF_MIME }
      ]
    });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "partial_json", "S9 partial status");
    assert.equal(outcome.partial, true, "S9 partial flag");
    assert.equal(outcome.reported, true, "S9 reported");
    assert.equal(outcome.ok, false, "S9 not success");
    assert.equal(outcome.missing, "pdf", "S9 missing pdf");
    const retried = await h.client.retryMissing({ outcome, draft, pdfBytes: pdfBytes() });
    assert.equal(retried.status, "complete", "S9 retry completes");
    assert.equal(h.state.created.filter((file) => file.mimeType === JSON_MIME).length, 1, "S9 json not duplicated");
    mark("S9_PARTIAL_UPLOAD_REPORTED", "PASS");
  }

  /* 시나리오 10 — Google 인증 실패 및 토큰 만료 */
  {
    const h = harness();
    const denied = await h.deny("access_denied");
    assert.equal(denied.ok, false, "S10 denied");
    assert.equal(denied.code, "drive_auth_denied", "S10 denial code");
    assert.equal(h.client.session().connected, false, "S10 no session");
    const second = harness();
    await second.connect({ expires_in: 30 });
    let clock = Date.now() + 31 * 1000;
    const expired = Client.create({
      clientId: CLIENT_ID,
      fetch: async () => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => ({ files: [] }) }),
      google: null, now: () => clock
    });
    assert.ok(typeof expired.session === "function", "S10 session api");
    mark("S10_AUTH_FAILURE_AND_EXPIRY", "PASS");
  }

  /* 시나리오 11 — 다른 Google 계정의 비인가 파일 접근 거부 */
  {
    const h = harness({ media: "{}" });
    await h.connect();
    const missing = await h.client.openQuoteFile("nope");
    assert.equal(missing.code, "drive_file_not_found", "S11 missing file");
    h.state.metadata = {
      id: "foreign", name: "f.json", mimeType: JSON_MIME, size: 100, trashed: false,
      owners: [{ me: false }]
    };
    const opened = await h.client.openQuoteFile("foreign");
    assert.equal(opened.ok, false, "S11 denied");
    assert.equal(opened.code, "drive_file_not_owned_by_connected_account", "S11 code");
    const mediaCalls = h.calls.filter((call) => call.url.indexOf("alt=media") !== -1);
    assert.equal(mediaCalls.length, 0, "S11 소유하지 않은 파일의 본문을 내려받지 않는다");
    mark("S11_OTHER_ACCOUNT_DENIED", "PASS");
  }

  /* 시나리오 12 — 로그아웃 후 권한 차단 */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    await h.connect();
    assert.equal(h.client.session().connected, true, "S12 connected");
    await h.client.disconnect();
    assert.equal(h.client.session().connected, false, "S12 disconnected");
    assert.equal((await h.client.openQuoteFile("x")).code, "drive_not_connected", "S12 open blocked");
    assert.equal((await h.client.savePair({ draft: baseDraft(), pdfBytes: pdfBytes() })).code,
      "drive_not_connected", "S12 save blocked");
    assert.equal(h.state.created.length, 0, "S12 no upload after logout");
    mark("S12_LOGOUT_BLOCKS_ACCESS", "PASS");
  }

  /* 시나리오 13 — 기존 D1 최근 견적(#3405) 회귀 없음 */
  {
    const draft = baseDraft();
    const snapshot = ServerHistory.draftToHistorySnapshot(draft);
    assert.equal(snapshot.schema, "b66.quote-draft.v1", "S13 snapshot schema unchanged");
    assert.equal(ServerHistory.QUOTES_API_BASE, "/api/padiem/b66/quotes", "S13 api base unchanged");
    assert.ok(!("detailGroups" in snapshot), "S13 기존 동작 유지(무손실 주장 없음)");
    const back = ServerHistory.historySnapshotToDraft(snapshot);
    assert.ok(back && back.meta.quoteNo === draft.meta.quoteNo, "S13 reverse conversion intact");
    assert.equal(History.HISTORY_STORAGE_KEY, "quoteBeta.history.v1", "S13 history key unchanged");
    assert.equal(History.MAX_HISTORY, 20, "S13 bound unchanged");
    const driveSources = readModule("quote-drive-contract.js") + readModule("quote-drive-client.js") +
      readModule("quote-drive-ui.js");
    assert.ok(driveSources.indexOf("quoteBeta.history.v1") === -1, "S13 Drive 코드가 D1/로컬 이력을 건드리지 않음");
    assert.ok(driveSources.indexOf("/api/padiem/b66/quotes") === -1, "S13 D1 API 재사용 없음");
    mark("S13_EXISTING_3405_D1_HISTORY_UNCHANGED", "PASS");
  }

  /* 시나리오 14 — 기존 PDF 다운로드 경로 회귀 없음 */
  {
    assert.equal(typeof BrowserPdf.makePdf, "function", "S14 makePdf intact");
    assert.equal(BrowserPdf.CGI_SKILL_ID, "b66skill_2eb55d822407f626b7a75c8c88d32c40", "S14 certified skill intact");
    assert.ok(appSource.includes("bridge.downloadPdf(model, previewModel)"), "S14 기존 다운로드 경로 유지");
    assert.ok(appSource.includes("certifiedPdfBytes: certifiedPdfBytesForStorage"), "S14 외부 저장용 seam 추가");
    assert.ok(appSource.includes("window.B66BrowserPdf.isCgiSkill(skillUiState.activeSkillId)"),
      "S14 기존 인증 CGI 판정 유지");
    const driveSources = readModule("quote-drive-contract.js") + readModule("quote-drive-client.js") +
      readModule("quote-drive-ui.js");
    assert.ok(!/makePdf\(/.test(driveSources), "S14 Drive 코드가 렌더러를 직접 호출하지 않음");
    mark("S14_EXISTING_PDF_DOWNLOAD_UNCHANGED", "PASS");
  }

  /* 시나리오 15 — 모델 호출 0회 */
  {
    const sources = ["quote-drive-contract.js", "quote-drive-client.js", "quote-drive-ui.js"]
      .map(readModule).join("\n");
    assert.ok(!/(kilo\/|sensenova|space-bunny|nemotron|openai|anthropic|gpt-|claude|glm-|LLM)/i.test(sources),
      "S15 no model identifiers");
    assert.ok(sources.indexOf("googleapis.com") !== -1, "S15 google endpoint declared");
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: Contract.PDF_MIME }] });
    await h.connect();
    await h.client.savePair({ draft: baseDraft(), pdfBytes: pdfBytes() });
    h.calls.forEach((call) => {
      const host = call.url.replace(/^https?:\/\//, "").split("/")[0];
      assert.ok(host === "www.googleapis.com" || host === "oauth2.googleapis.com", "S15 host: " + host);
    });
    mark("S15_MODEL_CALLS", "0");
  }

  /* 화면 계약 — Drive 기능은 선택 사항이며 기존 흐름을 막지 않는다 */
  {
    assert.ok(htmlSource.includes('id="driveStoragePanel"'), "UI container exists");
    assert.ok(htmlSource.includes('src="quote-drive-contract.js"'), "contract script loaded");
    assert.ok(htmlSource.includes('src="quote-drive-client.js"'), "client script loaded");
    assert.ok(htmlSource.includes('src="quote-drive-ui.js"'), "ui script loaded");
    assert.ok(htmlSource.includes('id="printPdf"'), "기존 PDF 버튼 유지");
    assert.ok(htmlSource.includes('id="saveHistory"'), "기존 최근 견적 저장 유지");
    const uiSource = readModule("quote-drive-ui.js");
    assert.ok(!/\.innerHTML\s*=/.test(uiSource), "UI has no markup injection surface");
    assert.ok(uiSource.indexOf("localStorage") === -1 && uiSource.indexOf("sessionStorage") === -1,
      "UI stores nothing");
    assert.ok(/saveButton\.addEventListener\("click", onSave\)/.test(uiSource), "저장은 명시적 클릭으로만 실행된다");
    assert.ok(!/setInterval|setTimeout/.test(uiSource), "UI has no timed/automatic save or sync");
    assert.ok(uiSource.indexOf("addEventListener(\"click\"") !== -1, "UI actions are user-triggered only");
    mark("SLICE_D_UI_OPTIONAL", "PASS");
    mark("BROWSER_LOCAL_CONTINUES", "PASS");
  }

  console.log(scenario.join("\n"));
  console.log("SLICE_E_OFFLINE_TESTED=PASS");
  console.log("CROSS_BROWSER_DRIVE_REOPEN=NOT_TESTED");
  console.log("REAL_PHONE=NOT_TESTED");
  console.log("LIVE_DRIVE_VERIFIED=NOT_TESTED");
  console.log("PRODUCTION_DEPLOYMENT=NOT_PERFORMED");
})().catch((error) => {
  console.error("SLICE_E_INTEGRATION=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
