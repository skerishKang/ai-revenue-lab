/* #3871 Slice E — 통합 검증 시나리오(오프라인).
   실제 Google 계정·실기기·운영 배포는 이 파일에서 검증하지 않는다.
   검증하지 못한 항목은 PASS 가 아니라 NOT_TESTED 로 남긴다. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");
const Ui = require("../quote-drive-ui.js");
const ServerHistory = require("../quote-history-server.js");
const History = require("../quote-history.js");
const BrowserPdf = require("../quote-browser-pdf.js");

const readModule = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const appSource = readModule("app.js");
const htmlSource = readModule("index.html");
const uiSource = readModule("quote-drive-ui.js");
const clientSource = readModule("quote-drive-client.js");
const contractSource = readModule("quote-drive-contract.js");

const CLIENT_ID = "test-client-id.apps.googleusercontent.com";
const JSON_MIME = Contract.JSON_MIME;
const PDF_MIME = Contract.PDF_MIME;
const SKILL_ID = "b66skill_2eb55d822407f626b7a75c8c88d32c40";
const TEMPLATE = { savedSkillId: SKILL_ID, fingerprint: "fp-cgi-v1" };
const APPROVED = [{ savedSkillId: SKILL_ID, fingerprint: "fp-cgi-v1", approved: true, active: true }];

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

function pdfBytes(marker) {
  const bytes = new Uint8Array(512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  if (marker) bytes[400] = marker;
  return bytes;
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

function harness(options) {
  const opts = options || {};
  const calls = [];
  const state = {
    files: (opts.files || []).slice(),
    metadataById: opts.metadataById || {},
    media: opts.media === undefined ? null : opts.media,
    uploadQueue: (opts.uploads || []).slice(),
    created: [],
    listStatus: 0,
    forcePageToken: false,
    beforeResponse: null
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
    if (typeof state.beforeResponse === "function") await state.beforeResponse(target);
    if (target.indexOf("oauth2.googleapis.com/revoke") !== -1) return jsonResponse({}, 200);
    if (target.indexOf("/upload/drive/v3/files") !== -1) {
      const next = state.uploadQueue.shift();
      if (!next) return jsonResponse({ error: { message: "no stub" } }, 500);
      if (next.status && next.status >= 400) {
        return jsonResponse(next.data || { error: { message: "stub" } }, next.status);
      }
      let name = "uploaded";
      try {
        const bodyText = Buffer.from(request.body).toString("utf8");
        const match = /"name"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(bodyText);
        if (match) name = JSON.parse('"' + match[1] + '"');
      } catch (err) { name = "uploaded"; }
      const id = "id-" + (state.created.length + 1);
      state.created.push({ id, name, mimeType: next.mimeType || "" });
      state.files.push({ id, name, mimeType: next.mimeType || "", trashed: false, owners: [{ me: true }] });
      return jsonResponse({ id, name });
    }
    if (target.indexOf("alt=media") !== -1) {
      return { ok: true, status: 200, headers: { get: () => null }, text: async () => String(state.media || "") };
    }
    if (target.indexOf("/drive/v3/files/") !== -1) {
      const rest = target.slice(target.indexOf("/drive/v3/files/") + "/drive/v3/files/".length);
      const id = decodeURIComponent(rest.split("?")[0]);
      const meta = state.metadataById[id];
      if (!meta) return jsonResponse({ error: { message: "not found" } }, 404);
      return jsonResponse(meta);
    }
    if (target.indexOf("/drive/v3/files?") !== -1) {
      if (state.listStatus >= 400) return jsonResponse({ error: { message: "list failed" } }, state.listStatus);
      const params = {};
      const queryIndex = target.indexOf("?");
      target.slice(queryIndex + 1).split("&").forEach((pair) => {
        const eq = pair.indexOf("=");
        params[decodeURIComponent(eq === -1 ? pair : pair.slice(0, eq))] =
          decodeURIComponent(eq === -1 ? "" : pair.slice(eq + 1));
      });
      const nameMatch = /name = '((?:[^'\\]|\\.)*)'/.exec(params.q || "");
      if (nameMatch) {
        const wanted = nameMatch[1].replace(/\\'/g, "'").replace(/\\\\/g, "\\");
        return jsonResponse({
          files: state.files.filter((file) => file.name === wanted).map((file) => ({ id: file.id, name: file.name }))
        });
      }
      const pageSize = Number(params.pageSize) || 100;
      const offset = params.pageToken ? Number(params.pageToken) : 0;
      const slice = state.files.slice(offset, offset + pageSize);
      const nextOffset = offset + pageSize;
      const body = { files: slice };
      if (nextOffset < state.files.length || state.forcePageToken) body.nextPageToken = String(nextOffset);
      return jsonResponse(body);
    }
    return jsonResponse({ error: { message: "unexpected endpoint" } }, 404);
  };
  let tokenCallback = null;
  const google = {
    accounts: {
      oauth2: {
        initTokenClient(config) { tokenCallback = config.callback; return { requestAccessToken() {} }; }
      }
    },
    picker: undefined
  };
  const client = Object.assign({}, Client.create({
    clientId: CLIENT_ID,
    appId: opts.appId || "",
    developerKey: opts.developerKey || "",
    fetch: fetchImpl,
    google: google,
    gapi: null,
    now: opts.now || (() => Date.now()),
    loadScript: async () => { throw new Error("no network in test"); }
  }));
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
const uploadCount = (h) => h.calls.filter((call) => call.url.indexOf("/upload/drive") !== -1).length;
const keepFile = (h, id, name, mimeType) => {
  h.state.metadataById[id] = {
    id, name, mimeType, size: 4000, trashed: false,
    owners: [{ me: true }], capabilities: { canDownload: true }
  };
};

(async () => {
  /* 시나리오 1 — 정상 JSON + PDF 저장 */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    await h.connect();
    const outcome = await h.client.savePair({ draft: baseDraft(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "S1 complete");
    assert.ok(outcome.json.name.endsWith(".json"), "S1 json name");
    assert.ok(outcome.pdf.name.endsWith(".pdf"), "S1 pdf name");
    assert.equal(h.state.created.length, 2, "S1 two uploads");
    mark("S1_NORMAL_JSON_PDF_SAVE", "PASS");
  }

  /* 시나리오 2 — 두 파일을 다시 찾아서 열기 */
  {
    const draft = baseDraft();
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    await h.connect();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    const listed = await h.client.listQuoteFiles();
    assert.equal(listed.ok, true, "S2 list ok");
    assert.equal(listed.files.length, 2, "S2 pair both discoverable");
    const jsonFile = listed.files.filter((file) => file.mimeType === JSON_MIME)[0];
    const built = Contract.buildPackage({
      draft, template: TEMPLATE, savedAt: "2026-10-09T09:00:00.000Z", packageId: outcome.packageId
    });
    keepFile(h, jsonFile.id, jsonFile.name, JSON_MIME);
    h.state.media = Contract.serializePackage(built.package);
    const opened = await h.client.openQuoteFile(jsonFile.id, { templates: APPROVED });
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

    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    await h.connect();
    const outcome = await h.client.savePair({ draft: edited, template: TEMPLATE, pdfBytes: pdfBytes() });
    keepFile(h, outcome.json.id, outcome.json.name, JSON_MIME);
    h.state.media = Contract.serializePackage(Contract.buildPackage({
      draft: edited, template: TEMPLATE, packageId: outcome.packageId
    }).package);
    const opened = await h.client.openQuoteFile(outcome.json.id, { templates: APPROVED });
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
    const raw = Contract.buildPackage({ draft, template: TEMPLATE, packageId: "pkg-tamper-2" }).package;
    raw.totals = { supply: 1, vat: 1, grand: 999999999 };
    const parsed = Contract.readPackage(JSON.stringify(raw), {});
    assert.equal(parsed.totalsIgnored, true, "S4 totals ignored");
    const imported = Contract.importPackage(parsed.package, { templates: APPROVED });
    const expected = Core.computeDraftTotals(draft);
    assert.equal(imported.totals.grand, expected.grand, "S4 recalculated");
    assert.notEqual(imported.totals.grand, 999999999, "S4 tampered value rejected");
    mark("S4_TAMPERED_TOTALS_RECALCULATED", "PASS");
  }

  /* 시나리오 4b — 견적 본문 변조는 거부 */
  {
    const draft = baseDraft();
    const raw = Contract.buildPackage({ draft, template: TEMPLATE, packageId: "pkg-body" }).package;
    raw.quote.items[1].unitPrice = 1;
    assert.equal(Contract.readPackage(JSON.stringify(raw), {}).code, "content_fingerprint_mismatch",
      "S4B_BODY_TAMPER_REJECTED");
    mark("S4B_QUOTE_BODY_TAMPER_REJECTED", "PASS");
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
    const pkg = Contract.buildPackage({ draft, template: TEMPLATE, packageId: "pkg-v" }).package;
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
    const h = harness({ uploads: [] });
    await h.connect();
    const outcome = await h.client.savePair({ draft: baseDraft(), template: TEMPLATE, pdfBytes: wrong });
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
      uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }]
    });
    await h.connect();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "S8 save ok");
    assert.notEqual(outcome.json.name, first.json, "S8 renamed");
    assert.equal(h.state.files.filter((file) => file.name === first.json).length, 1, "S8 original kept");
    mark("S8_DUPLICATE_NAME_NO_OVERWRITE", "PASS");
  }

  /* 시나리오 8b — 이름 점검 실패/잘림은 저장 거부(fail-closed) */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    await h.connect();
    h.state.listStatus = 500;
    const failed = await h.client.savePair({ draft: baseDraft(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(failed.code, "naming_check_unavailable", "S8B_NAMING_CHECK_UNAVAILABLE");
    assert.equal(uploadCount(h), 0, "S8B no upload on naming failure");
    h.state.listStatus = 0;
    h.state.forcePageToken = true;
    const truncated = await h.client.savePair({ draft: baseDraft(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(truncated.code, "naming_check_incomplete", "S8B_NAMING_CHECK_INCOMPLETE");
    assert.equal(uploadCount(h), 0, "S8B no upload on truncated list");
    mark("S8B_NAMING_CHECK_FAILS_CLOSED", "PASS");
  }

  /* 시나리오 8c — 목록 페이지 전체 수집 */
  {
    const files = [];
    for (let index = 0; index < 6; index += 1) {
      files.push({ id: "f" + index, name: "n" + index + ".json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] });
    }
    const h = harness({ files: files });
    await h.connect();
    const listed = await h.client.listQuoteFiles({ pageSize: 2 });
    assert.equal(listed.files.length, 6, "S8C all pages collected");
    assert.equal(listed.pages, 3, "S8C three pages");
    assert.equal(listed.truncated, false, "S8C not truncated");
    mark("S8C_LIST_PAGINATION", "PASS");
  }

  /* 시나리오 9 — JSON 성공·PDF 실패의 부분 저장 상태 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } },
        { mimeType: PDF_MIME }
      ]
    });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "partial_json", "S9 partial status");
    assert.equal(outcome.reported, true, "S9 reported");
    assert.equal(outcome.ok, false, "S9 not success");
    assert.equal(outcome.missing, "pdf", "S9 missing pdf");
    keepFile(h, outcome.json.id, outcome.pair.jsonName, JSON_MIME);
    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.status, "complete", "S9 retry completes");
    assert.equal(retried.json.name, outcome.pair.jsonName, "S9 original json name kept");
    assert.equal(h.state.created.filter((file) => file.mimeType === JSON_MIME).length, 1, "S9 json not duplicated");
    mark("S9_PARTIAL_UPLOAD_REPORTED", "PASS");
  }

  /* 시나리오 9b — PDF 성공·JSON 실패 후 재시도 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME, status: 403, data: { error: { message: "denied" } } },
        { mimeType: PDF_MIME },
        { mimeType: JSON_MIME }
      ]
    });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "partial_pdf", "S9B partial pdf");
    assert.equal(outcome.missing, "json", "S9B missing json");
    keepFile(h, outcome.pdf.id, outcome.pair.pdfName, PDF_MIME);
    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.status, "complete", "S9B retry completes");
    assert.equal(retried.pdf.name, outcome.pair.pdfName, "S9B original pdf name kept");
    assert.equal(h.state.created.filter((file) => file.mimeType === PDF_MIME).length, 1, "S9B pdf not duplicated");
    mark("S9B_PARTIAL_PDF_RETRY", "PASS");
  }

  /* 시나리오 9c — 재시도 사이 견적이 바뀌면 새 쌍을 요구한다 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    keepFile(h, outcome.json.id, outcome.pair.jsonName, JSON_MIME);
    const edited = Core.normalizeDraft(Object.assign({}, draft, {
      items: [{ id: "item-1", name: "서비스 구축", qty: 5, unitPrice: 1000000 }]
    }));
    const before = uploadCount(h);
    const retried = await h.client.retryMissing({ outcome, draft: edited, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.code, "pending_pair_stale", "S9C edited draft blocked");
    assert.equal(uploadCount(h), before, "S9C no upload on stale pair");
    mark("S9C_EDITED_DRAFT_BLOCKS_RETRY", "PASS");
  }

  /* 시나리오 9d — 재시도 사이 PDF 가 바뀌면 새 쌍을 요구한다 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    keepFile(h, outcome.json.id, outcome.pair.jsonName, JSON_MIME);
    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes(9) });
    assert.equal(retried.code, "pending_pdf_changed", "S9D changed pdf blocked");
    mark("S9D_CHANGED_PDF_BLOCKS_RETRY", "PASS");
  }

  /* 시나리오 9e — 유지된 파일이 사라졌으면 완료를 주장하지 않는다 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.code, "kept_file_unavailable", "S9E kept file missing");
    assert.equal(uploadCount(h), 2, "S9E no upload without kept file");
    mark("S9E_KEPT_FILE_VERIFIED_BEFORE_COMPLETE", "PASS");
  }

  /* 시나리오 9f — 재시도 시 고정 이름이 점유되면 새 저장 요구 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    await h.connect();
    const draft = baseDraft();
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    keepFile(h, outcome.json.id, outcome.pair.jsonName, JSON_MIME);
    h.state.files.push({ id: "squat", name: outcome.pair.pdfName, mimeType: PDF_MIME, trashed: false, owners: [{ me: true }] });
    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.code, "duplicate_name_conflict", "S9F frozen name taken");
    mark("S9F_FROZEN_NAME_TAKEN_BLOCKS_RETRY", "PASS");
  }

  /* 시나리오 10 — Google 인증 실패 및 토큰 만료 */
  {
    const h = harness();
    const denied = await h.deny("access_denied");
    assert.equal(denied.code, "drive_auth_denied", "S10 denial code");
    assert.equal(h.client.session().connected, false, "S10 no session");

    let clock = 1000000;
    const expired = harness({ now: () => clock });
    await expired.connect({ expires_in: 60 });
    clock += 61 * 1000;
    assert.equal((await expired.client.listQuoteFiles()).code, "drive_token_expired", "S10 token expiry");
    mark("S10_AUTH_FAILURE_AND_EXPIRY", "PASS");
  }

  /* 시나리오 11 — 다른 Google 계정/소유 미확인 파일 접근 거부 */
  {
    const h = harness({
      metadataById: {
        foreign: { id: "foreign", name: "f.json", mimeType: JSON_MIME, size: 100, trashed: false, owners: [{ me: false }] },
        noOwners: { id: "noOwners", name: "n.json", mimeType: JSON_MIME, size: 100, trashed: false },
        emptyOwners: { id: "emptyOwners", name: "e.json", mimeType: JSON_MIME, size: 100, trashed: false, owners: [] }
      },
      media: "{}"
    });
    await h.connect();
    const mediaCount = () => h.calls.filter((call) => call.url.indexOf("alt=media") !== -1).length;
    assert.equal((await h.client.openQuoteFile("foreign")).code,
      "drive_file_not_owned_by_connected_account", "S11 foreign denied");
    assert.equal((await h.client.openQuoteFile("noOwners")).code,
      "drive_file_ownership_unverified", "S11 missing owners denied");
    assert.equal((await h.client.openQuoteFile("emptyOwners")).code,
      "drive_file_ownership_unverified", "S11 empty owners denied");
    assert.equal(mediaCount(), 0, "S11 no media fetched before ownership verification");
    assert.equal((await h.client.openQuoteFile("nope")).code, "drive_file_not_found", "S11 missing file");
    mark("S11_OTHER_ACCOUNT_AND_UNVERIFIED_DENIED", "PASS");
  }

  /* 시나리오 12 — 로그아웃 후 권한 차단 */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    await h.connect();
    await h.client.disconnect();
    assert.equal((await h.client.openQuoteFile("x")).code, "drive_not_connected", "S12 open blocked");
    assert.equal((await h.client.savePair({ draft: baseDraft(), pdfBytes: pdfBytes() })).code,
      "drive_not_connected", "S12 save blocked");
    assert.equal(h.state.created.length, 0, "S12 no upload after logout");
    mark("S12_LOGOUT_BLOCKS_ACCESS", "PASS");
  }

  /* 시나리오 12b — B66 로그아웃/계정 전환이 Drive 세션을 폐기한다 */
  {
    const handlers = {};
    const container = { replaceChildren() {}, appendChild() {} };
    const doc = {
      createElement: () => ({ appendChild() {}, addEventListener() {}, replaceChildren() {}, dataset: {} }),
      getElementById: () => container,
      addEventListener(type, handler) { (handlers[type] = handlers[type] || []).push(handler); },
      dispatch(type, detail) { (handlers[type] || []).forEach((handler) => handler({ detail: detail })); }
    };
    const h = harness({ uploads: [] });
    await h.connect();
    const ui = Ui.mount({
      document: doc, client: h.client, contract: Contract,
      bridge: { getDraft: () => baseDraft(), replaceDraft: () => ({ ok: true }), listApprovedSkills: () => APPROVED }
    });
    assert.equal(ui.ok, true, "S12B mounted");
    assert.equal(h.client.session().connected, true, "S12B connected");
    doc.dispatch("b66:auth-changed", { authenticated: false });
    assert.equal(h.client.session().connected, false, "S12B b66 logout clears drive session");
    await h.connect();
    doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: false, action: "quarantined_foreign_owner"
    });
    assert.equal(h.client.session().connected, false, "S12B account switch clears drive session");
    mark("S12B_B66_LOGOUT_AND_SWITCH_ISOLATION", "PASS");
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
    const driveSources = contractSource + clientSource + uiSource;
    assert.ok(driveSources.indexOf("quoteBeta.history.v1") === -1, "S13 Drive 코드가 로컬 이력을 건드리지 않음");
    assert.ok(driveSources.indexOf("/api/padiem/b66/quotes") === -1, "S13 D1 API 재사용 없음");
    mark("S13_EXISTING_3405_D1_HISTORY_UNCHANGED", "PASS");
  }

  /* 시나리오 14 — 기존 PDF 다운로드 경로 회귀 없음 */
  {
    assert.equal(typeof BrowserPdf.makePdf, "function", "S14 makePdf intact");
    assert.equal(BrowserPdf.CGI_SKILL_ID, SKILL_ID, "S14 certified skill intact");
    assert.ok(appSource.includes("bridge.downloadPdf(model, previewModel)"), "S14 기존 다운로드 경로 유지");
    assert.ok(appSource.includes("certifiedPdfBytes: certifiedPdfBytesForStorage"), "S14 외부 저장용 seam 추가");
    assert.ok(appSource.includes("window.B66BrowserPdf.isCgiSkill(skillUiState.activeSkillId)"),
      "S14 기존 인증 CGI 판정 유지");
    assert.ok(!/makePdf\(/.test(contractSource + clientSource + uiSource), "S14 Drive 코드가 렌더러를 직접 호출하지 않음");
    mark("S14_EXISTING_PDF_DOWNLOAD_UNCHANGED", "PASS");
  }

  /* 시나리오 15 — 모델 호출 0회 */
  {
    const sources = contractSource + clientSource + uiSource;
    assert.ok(!/(kilo\/|sensenova|space-bunny|nemotron|openai|anthropic|gpt-|claude|glm-)/i.test(sources),
      "S15 no model identifiers");
    assert.ok(sources.indexOf("googleapis.com") !== -1, "S15 google endpoint declared");
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    await h.connect();
    await h.client.savePair({ draft: baseDraft(), template: TEMPLATE, pdfBytes: pdfBytes() });
    h.calls.forEach((call) => {
      const host = call.url.replace(/^https?:\/\//, "").split("/")[0];
      assert.ok(host === "www.googleapis.com" || host === "oauth2.googleapis.com", "S15 host: " + host);
    });
    mark("S15_MODEL_CALLS", "0");
  }

  /* 화면/부트스트랩 계약 — Drive 기능은 선택 사항이며 기존 흐름을 막지 않는다 */
  {
    assert.ok(htmlSource.includes('id="driveStoragePanel"'), "UI container exists");
    assert.ok(htmlSource.includes('src="quote-drive-contract.js"'), "contract script loaded");
    assert.ok(htmlSource.includes('src="quote-drive-client.js"'), "client script loaded");
    assert.ok(htmlSource.includes('src="quote-drive-ui.js"'), "ui script loaded");
    assert.ok(htmlSource.includes('id="printPdf"'), "기존 PDF 버튼 유지");
    assert.ok(htmlSource.includes('id="saveHistory"'), "기존 최근 견적 저장 유지");
    assert.ok(/installStartHook\(window, api\)/.test(uiSource), "UI_SELF_START_HOOK_PRESENT");
    assert.ok(/bootstrapState\.handle/.test(uiSource), "UI_BOOTSTRAP_IDEMPOTENT_GUARD");
    assert.ok(appSource.includes("listApprovedSkills"), "APPROVED_SKILL_LIST_BRIDGE_PRESENT");
    assert.ok(!/\.innerHTML\s*=/.test(uiSource), "UI has no markup injection surface");
    assert.ok(uiSource.indexOf("localStorage") === -1 && uiSource.indexOf("sessionStorage") === -1,
      "UI stores nothing");
    assert.ok(/saveButton\.addEventListener\("click", onSave\)/.test(uiSource), "저장은 명시적 클릭으로만 실행된다");
    assert.ok(!/setInterval/.test(uiSource), "UI has no automatic repeat save or sync");
    assert.ok(/onSave[\s\S]*?client\.savePair/.test(uiSource), "SAVE_ONLY_INSIDE_CLICK_HANDLER");
    mark("SLICE_D_UI_OPTIONAL", "PASS");
    mark("BROWSER_LOCAL_CONTINUES", "PASS");
  }

  /* 시나리오 16 — 로그인 버튼부터 로그아웃·계정 전환까지 실제 흐름 계약 */
  {
    /* 정상 로그인/상태 갱신은 세션을 유지하고, 권위 상실·변경만 폐기한다. */
    assert.deepEqual(Ui.DRIVE_SESSION_KEEP_ACTIONS.slice(), ["owner_bound", "same_account_resume"],
      "S16_KEEP_ACTIONS");
    ["quarantined_foreign_owner", "quarantined_malformed_owner",
      "authenticated_owner_unusable", "unresolved"].forEach((action) => {
      assert.ok(Ui.DRIVE_SESSION_DROP_ACTIONS.indexOf(action) !== -1, "S16_DROP_ACTION: " + action);
    });
    /* 팝업 대기 중 계정 변경이 뒤늦은 토큰을 막는다. */
    assert.ok(/startedEpoch/.test(clientSource), "S16_CONNECT_CAPTURES_EPOCH");
    assert.ok(/drive_auth_superseded/.test(clientSource), "S16_LATE_TOKEN_REJECTED_CODE");
    assert.ok(/connectPending/.test(clientSource), "S16_CONNECT_IN_PROGRESS_GUARD");
    /* 폐기는 세션이 없어도 세대를 올린다. */
    assert.ok(/client\.disconnect\(\{ reason: reason \}\)/.test(uiSource), "S16_ALWAYS_BUMPS_EPOCH");
    mark("S16_LOGIN_TO_SWITCH_FLOW", "PASS (see quote-drive-account-flow.test.cjs)");
  }

  /* 시나리오 17 — 다른 승인 템플릿 견적 불러오기는 편집 내용을 보호한다 */
  {
    assert.ok(/templateMatches/.test(uiSource), "S17_TEMPLATE_MATCH_CHECK_PRESENT");
    assert.ok(/hasMeaningfulDraft/.test(uiSource), "S17_EDITOR_CONTENT_CHECK_PRESENT");
    assert.ok(appSource.includes("hasMeaningfulDraft"), "S17_BRIDGE_EXPOSES_EDITOR_CONTENT_STATE");
    assert.ok(!/opts\.confirm\([^)]*\)\s*:\s*true/.test(uiSource), "S17_NO_DEFAULT_TRUE_CONFIRM");
    mark("S17_OTHER_TEMPLATE_PROTECTS_EDITOR", "PASS (see quote-drive-account-flow.test.cjs)");
  }

  /* 시나리오 18 — 불러오기 실패는 편집기 내용·템플릿을 바꾸지 않는다(원자성) */
  {
    const atomicSource = readModule("quote-import-atomic.js");
    assert.ok(htmlSource.includes('src="quote-import-atomic.js"'), "S18_ATOMIC_SCRIPT_LOADED");
    assert.ok(atomicSource.indexOf("beforeApply") !== -1, "S18_COMMIT_POINT_GUARD_PRESENT");
    assert.ok(atomicSource.indexOf("restore") !== -1, "S18_ROLLBACK_PRESENT");
    /* UI 는 원자적 브리지 연산만 사용한다(2단계 replaceDraft 직접 호출 금지) */
    assert.ok(/bridge\.applyImportedDraft\(/.test(uiSource), "S18_UI_USES_ATOMIC_BRIDGE");
    assert.ok(!/bridge\.replaceDraft\(/.test(uiSource), "S18_UI_NO_DIRECT_REPLACE_DRAFT");
    /* 복구가 확인되지 않으면 보존을 주장하지 않는다 */
    assert.ok(/result\.preserved === true/.test(uiSource), "S18_UI_BRANCHES_ON_PRESERVED");
    assert.ok(/복구했다고 확인하지 못했습니다/.test(uiSource), "S18_UI_HARD_FAILURE_MESSAGE");
    assert.ok(appSource.includes("applyImportedDraft"), "S18_BRIDGE_EXPOSES_ATOMIC_APPLY");
    assert.ok(appSource.includes("snapshotEditorState"), "S18_BRIDGE_SNAPSHOTS_EDITOR");
    assert.ok(appSource.includes("restoreEditorState"), "S18_BRIDGE_RESTORES_EDITOR");
    mark("S18_IMPORT_FAILURE_PRESERVES_EDITOR",
      "PASS (see quote-import-atomic.test.cjs, quote-drive-import-safety.test.cjs)");
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
