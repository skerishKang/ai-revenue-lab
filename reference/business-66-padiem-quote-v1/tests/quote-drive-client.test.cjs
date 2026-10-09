/* #3871 Slice B/C — Google Drive 연결·저장·불러오기 오프라인 테스트.
   실제 Google 계정·네트워크·모델 호출은 사용하지 않는다. 모든 통신은 주입된 스텁이다. */
const assert = require("node:assert");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");

const CLIENT_ID = "test-client-id.apps.googleusercontent.com";
const JSON_MIME = Contract.JSON_MIME;
const PDF_MIME = Contract.PDF_MIME;

function draftFixture() {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: "PQ-20261009-002", issueDate: "2026-10-09", validDays: 30, source: "manual" },
    sender: { company: "공급상사", rep: "김대표", bizNo: "123-45-67890", address: "서울", phone: "02-000-0000", email: "s@example.com", presetId: "custom" },
    recipient: { company: "가나상사", person: "박담당", address: "부산", email: "b@example.com" },
    items: [
      { id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 },
      { id: "item-2", name: "운영 지원", qty: 2, unitPrice: 300000 }
    ],
    detailGroups: [
      { id: "group-1", summaryItemId: "item-1", title: "구축 상세", items: [
        { id: "detail-1", name: "설계", qty: 1, unitPrice: 600000 },
        { id: "detail-2", name: "개발", qty: 1, unitPrice: 400000 }
      ] }
    ],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    calculationPolicy: { grandRounding: { mode: "FLOOR", unit: 100 } },
    memo: "메모"
  });
}

function pdfBytes() {
  const bytes = new Uint8Array(512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  return bytes;
}

function packageTextFor(draft, packageId) {
  const built = Contract.buildPackage({
    draft,
    template: { savedSkillId: "b66skill_2eb55d822407f626b7a75c8c88d32c40", fingerprint: "fp-cgi-v1" },
    savedAt: "2026-10-09T09:00:00.000Z",
    packageId: packageId || "pkg-client-0001"
  });
  return Contract.serializePackage(built.package);
}

/* ── 스텁 하네스 ── */
function harness(options) {
  const opts = options || {};
  const calls = [];
  const state = {
    files: opts.files || [],          // drive 목록 응답
    metadata: opts.metadata || null,  // files.get 메타데이터
    media: opts.media || null,        // alt=media 본문
    uploadQueue: (opts.uploads || []).slice()
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
    calls.push({ url: target, method: (init && init.method) || "GET", headers: (init && init.headers) || {} });
    const request = init || {};

    if (target.indexOf("oauth2.googleapis.com/revoke") !== -1) {
      return jsonResponse({}, 200);
    }
    if (target.indexOf("/upload/drive/v3/files") !== -1) {
      const next = state.uploadQueue.shift();
      if (!next) return jsonResponse({ error: { message: "no stub" } }, 500);
      if (typeof next === "function") return next(request.body, request.headers);
      return jsonResponse(next.data === undefined ? { id: "new-file-id", name: "file" } : next.data, next.status);
    }
    if (target.indexOf("alt=media") !== -1) {
      return { ok: true, status: 200, headers: { get: () => null }, text: async () => String(state.media || "") };
    }
    if (target.indexOf("/drive/v3/files/") !== -1) {
      if (state.metadata === null) return jsonResponse({ error: { message: "not found" } }, 404);
      return jsonResponse(state.metadata, state.metadataStatus || 200);
    }
    if (target.indexOf("/drive/v3/files?") !== -1) {
      return jsonResponse({ files: state.files }, 200);
    }
    return jsonResponse({ error: { message: "unexpected endpoint" } }, 404);
  };

  let tokenCallback = null;
  const google = {
    accounts: {
      oauth2: {
        initTokenClient(config) {
          state.lastScope = config.scope;
          state.lastClientId = config.client_id;
          tokenCallback = config.callback;
          return { requestAccessToken(request) { state.lastPrompt = request && request.prompt; } };
        }
      }
    },
    picker: undefined
  };

  const client = Client.create({
    clientId: opts.clientId === undefined ? CLIENT_ID : opts.clientId,
    fetch: fetchImpl,
    google: google,
    gapi: null,
    now: opts.now || (() => Date.now()),
    loadScript: async () => { throw new Error("no network in test"); }
  });

  return {
    client,
    calls,
    state,
    google,
    async approve(params) {
      await flush();
      tokenCallback(Object.assign({
        access_token: "stub-access-token",
        expires_in: 3600,
        scope: Client.SCOPE_DRIVE_FILE
      }, params || {}));
    },
    async deny(errorName) {
      await flush();
      tokenCallback({ error: errorName || "access_denied" });
    }
  };
}

/* initTokenClient 는 connect() 내부의 비동 체인에서 호출되므로 한 틱 비워 준다. */
const flush = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
  /* ── 1. 설정 없이는 실패(조용한 무동작이 아니라 명시 코드) ── */
  {
    const h = harness({ clientId: "" });
    const result = await h.client.connect();
    assert.equal(result.ok, false, "미설정 연결 거부");
    assert.equal(result.code, "drive_not_configured", "DRIVE_NOT_CONFIGURED");
    assert.equal(h.client.isConfigured(), false, "isConfigured false");
  }

  /* ── 2. 연결 성공: 최소 권한 drive.file 만 요청 ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await flush();
    assert.equal(h.state.lastScope, Client.SCOPE_DRIVE_FILE, "LEAST_SCOPE_REQUESTED=drive.file");
    assert.equal(h.state.lastScope.indexOf("drive.readonly"), -1, "NO_BLANKET_DRIVE_SCOPE");
    assert.equal(h.state.lastClientId, CLIENT_ID, "client id forwarded");
    await h.approve();
    const result = await pending;
    assert.equal(result.ok, true, "connect ok");
    assert.deepEqual(result.scopes, [Client.SCOPE_DRIVE_FILE], "GRANTED_SCOPE=drive.file");
    assert.equal(h.client.session().connected, true, "SESSION_CONNECTED");
  }

  /* ── 3. 동의 취소/실패는 토큰 없이 명시 코드로 돌아온다 ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await flush();
    await h.deny("popup_closed");
    const result = await pending;
    assert.equal(result.ok, false, "denied");
    assert.equal(result.code, "drive_auth_denied", "DRIVE_AUTH_DENIED");
    assert.equal(h.client.session().connected, false, "DENIED_LEAVES_NO_SESSION");
    const list = await h.client.listQuoteFiles();
    assert.equal(list.code, "drive_not_connected", "DENIED_THEN_NOT_CONNECTED");
  }

  /* ── 4. JSON + PDF 한 쌍 저장: 항상 새 파일 생성(덮어쓰기 없음) ── */
  {
    const h = harness({
      files: [],
      uploads: [
        { data: { id: "json-file-id", name: "견적서_PQ-20261009-002_가나상사.json" } },
        { data: { id: "pdf-file-id", name: "견적서_PQ-20261009-002_가나상사.pdf" } }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({
      draft: draftFixture(),
      template: { savedSkillId: "b66skill_2eb55d822407f626b7a75c8c88d32c40", fingerprint: "fp-cgi-v1" },
      pdfBytes: pdfBytes(),
      packageId: "pkg-client-0001"
    });
    assert.equal(outcome.status, "complete", "SAVE_PAIR_COMPLETE");
    assert.equal(outcome.partial, false, "SAVE_PAIR_NOT_PARTIAL");
    assert.equal(outcome.json.id, "json-file-id", "JSON_FILE_ID");
    assert.equal(outcome.pdf.id, "pdf-file-id", "PDF_FILE_ID");
    assert.equal(outcome.packageId, "pkg-client-0001", "PAIR_SHARES_PACKAGE_ID");
    const uploads = h.calls.filter((call) => call.url.indexOf("/upload/drive") !== -1);
    assert.equal(uploads.length, 2, "TWO_UPLOADS");
    assert.equal(uploads[0].method, "POST", "UPLOAD_IS_CREATE_NOT_UPDATE");
    assert.ok(uploads[0].url.indexOf("uploadType=multipart") !== -1, "MULTIPART_UPLOAD");
    assert.ok(!/\/drive\/v3\/files\/[^?]+\?.*uploadType/.test(uploads[0].url), "NO_OVERWRITE_URL");
  }

  /* ── 5. 같은 이름이 있으면 덮어쓰지 않고 접미사를 붙인다 ── */
  {
    const existing = "견적서_PQ-20261009-002_가나상사.json";
    const h = harness({
      files: [{ id: "old", name: existing, mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      uploads: [
        { data: { id: "json-2", name: "견적서_PQ-20261009-002_가나상사-2.json" } },
        { data: { id: "pdf-2", name: "견적서_PQ-20261009-002_가나상사.pdf" } }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft: draftFixture(), pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "duplicate handled");
    assert.equal(outcome.renamed, true, "DUPLICATE_RENAMED");
    assert.notEqual(outcome.json.name, existing, "EXISTING_FILE_NOT_OVERWRITTEN");
  }

  /* ── 6. 부분 실패(JSON 성공·PDF 실패) → 정확한 상태 + 복구 재시도 ── */
  {
    const h = harness({
      files: [],
      uploads: [
        { data: { id: "json-file-id", name: "a.json" } },
        { status: 403, data: { error: { message: "storage quota exceeded" } } },
        { data: { id: "pdf-file-id", name: "a.pdf" } }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const draft = draftFixture();
    const outcome = await h.client.savePair({ draft, pdfBytes: pdfBytes(), packageId: "pkg-partial" });
    assert.equal(outcome.status, "partial_json", "PARTIAL_JSON_REPORTED");
    assert.equal(outcome.partial, true, "PARTIAL_FLAG");
    assert.equal(outcome.ok, false, "PARTIAL_IS_NOT_SUCCESS");
    assert.equal(outcome.missing, "pdf", "MISSING_PDF");
    assert.equal(outcome.retryable, true, "PARTIAL_RETRYABLE");
    assert.equal(outcome.reported, true, "PARTIAL_REPORTED_NOT_SILENT");

    const retried = await h.client.retryMissing({ outcome, draft, pdfBytes: pdfBytes() });
    assert.equal(retried.status, "complete", "RETRY_MISSING_COMPLETES");
    assert.equal(retried.pdf.id, "pdf-file-id", "PDF_UPLOADED_ON_RETRY");
    assert.equal(retried.json.id, "json-file-id", "JSON_NOT_DUPLICATED_ON_RETRY");
    const uploads = h.calls.filter((call) => call.url.indexOf("/upload/drive") !== -1);
    assert.equal(uploads.length, 3, "RETRY_UPLOADS_ONLY_THE_MISSING_SIDE");
  }

  /* ── 7. PDF 바이트가 잘못되면 아무것도 올리지 않는다(외톨이 파일 없음) ── */
  {
    const h = harness({ files: [], uploads: [] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft: draftFixture(), pdfBytes: null });
    assert.equal(outcome.status, "failed", "INVALID_PDF_BLOCKS_SAVE");
    assert.equal(outcome.code, "pdf_missing", "PDF_MISSING_CODE");
    assert.equal(h.calls.filter((call) => call.url.indexOf("/upload/drive") !== -1).length, 0,
      "NO_ORPHAN_UPLOAD");
  }

  /* ── 8. 다시 열기: 소유 검증 + QuoteCore 재계산 ── */
  {
    const draft = draftFixture();
    const text = packageTextFor(draft, "pkg-client-0001");
    const h = harness({
      files: [],
      metadata: {
        id: "file-1",
        name: "견적서_PQ-20261009-002_가나상사.json",
        mimeType: JSON_MIME,
        size: Buffer.byteLength(text, "utf8"),
        trashed: false,
        modifiedTime: "2026-10-09T09:00:00.000Z",
        owners: [{ me: true }]
      },
      media: text
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const opened = await h.client.openQuoteFile("file-1", {
      templates: [{ savedSkillId: "b66skill_2eb55d822407f626b7a75c8c88d32c40", fingerprint: "fp-cgi-v1", approved: true, active: true }]
    });
    assert.equal(opened.ok, true, "OPEN_OK");
    assert.equal(opened.totalsAuthority, "quote-core", "OPEN_TOTALS_AUTHORITY=quote-core");
    assert.deepEqual(opened.draft, draft, "REOPEN_DRAFT_IDENTICAL");
    const expected = Core.computeDraftTotals(draft);
    assert.deepEqual(
      [opened.totals.supply, opened.totals.vat, opened.totals.grand],
      [expected.supply, expected.vat, expected.grand],
      "REOPEN_RECALCULATED_BY_QUOTECORE"
    );
    assert.equal(opened.template.status, "resolved", "TEMPLATE_RESOLVED_ON_REOPEN");
    assert.equal(opened.file.id, "file-1", "OPENED_FILE_ID");
  }

  /* ── 9. 저장된 합계를 변조한 파일도 QuoteCore 값으로 다시 계산한다 ── */
  {
    const draft = draftFixture();
    const raw = JSON.parse(packageTextFor(draft, "pkg-tamper"));
    raw.totals = { supply: 7, vat: 7, grand: 7 };
    const text = JSON.stringify(raw);
    const h = harness({
      metadata: { id: "file-t", name: "t.json", mimeType: JSON_MIME, size: Buffer.byteLength(text, "utf8"), trashed: false, owners: [{ me: true }] },
      media: text
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const opened = await h.client.openQuoteFile("file-t");
    assert.equal(opened.ok, true, "tampered file opens");
    assert.equal(opened.totalsIgnored, true, "STORED_TOTALS_IGNORED_ON_REOPEN");
    const expected = Core.computeDraftTotals(draft);
    assert.equal(opened.totals.grand, expected.grand, "TAMPERED_TOTALS_RECALCULATED");
    assert.notEqual(opened.totals.grand, 7, "변조값 미반영");
  }

  /* ── 10. 다른 Google 계정 파일 / 없는 파일 / 휴지통 파일 거부 ── */
  {
    const h = harness({ metadata: null });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const missing = await h.client.openQuoteFile("does-not-exist");
    assert.equal(missing.code, "drive_file_not_found", "FOREIGN_OR_MISSING_FILE_NOT_FOUND");

    h.state.metadata = { id: "f2", name: "other.json", mimeType: JSON_MIME, size: 100, trashed: false, owners: [{ me: false, emailAddress: "someone@example.com" }] };
    const foreign = await h.client.openQuoteFile("f2");
    assert.equal(foreign.code, "drive_file_not_owned_by_connected_account", "OTHER_GOOGLE_ACCOUNT_DENIED");
    assert.ok(foreign.message && foreign.message.length > 0, "DENIAL_EXPLAINED");

    h.state.metadata = { id: "f3", name: "trashed.json", mimeType: JSON_MIME, size: 100, trashed: true, owners: [{ me: true }] };
    const trashed = await h.client.openQuoteFile("f3");
    assert.equal(trashed.code, "drive_file_trashed", "TRASHED_FILE_REJECTED");

    h.state.metadataStatus = 403;
    h.state.metadata = { id: "f4", name: "x.json", mimeType: JSON_MIME, size: 10, owners: [{ me: true }] };
    const denied = await h.client.openQuoteFile("f4");
    assert.equal(denied.code, "drive_file_access_denied", "ACCESS_DENIED_SURFACED");
  }

  /* ── 11. 목록은 소유하지 않은/휴지통 파일을 걸러낸다 ── */
  {
    const h = harness({
      files: [
        { id: "a", name: "mine.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] },
        { id: "b", name: "not-mine.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: false }] },
        { id: "c", name: "gone.json", mimeType: JSON_MIME, trashed: true, owners: [{ me: true }] },
        { id: "d", name: "shared.pdf", mimeType: PDF_MIME, trashed: false, owners: [] }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const list = await h.client.listQuoteFiles();
    assert.equal(list.ok, true, "list ok");
    assert.deepEqual(list.files.map((file) => file.id).sort(), ["a", "d"], "LIST_ONLY_VISIBLE_OWNED_FILES");
  }

  /* ── 12. 로그아웃 후 권한 차단 + 계정 전환 격리 ── */
  {
    const h = harness({ files: [] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    assert.equal(h.client.session().connected, true, "connected before logout");
    const out = await h.client.disconnect();
    assert.equal(out.code, "signed_out", "SIGNED_OUT");
    assert.equal(out.revoked, true, "TOKEN_REVOKED_ON_LOGOUT");
    assert.equal(h.client.session().connected, false, "LOGOUT_CLEARS_SESSION");
    const after = await h.client.openQuoteFile("file-1");
    assert.equal(after.code, "drive_not_connected", "LOGOUT_BLOCKS_ACCESS");
    const saveAfter = await h.client.savePair({ draft: draftFixture(), pdfBytes: pdfBytes() });
    assert.equal(saveAfter.code, "drive_not_connected", "LOGOUT_BLOCKS_SAVE");

    /* 계정 전환: select_account 프롬프트로 다시 연결 */
    const second = h.client.connect({ prompt: "select_account" });
    await flush();
    assert.equal(h.state.lastPrompt, "select_account", "ACCOUNT_SWITCH_PROMPT");
    await h.approve();
    const secondResult = await second;
    assert.equal(secondResult.ok, true, "reconnect ok");
    assert.equal(h.client.session().connected, true, "SWITCHED_ACCOUNT_CONNECTED");
  }

  /* ── 13. 토큰 만료는 만료 코드로 표면화된다 ── */
  {
    let clock = 1000000;
    const h = harness({ files: [], now: () => clock });
    const pending = h.client.connect();
    await h.approve({ expires_in: 60 });
    await pending;
    assert.equal(h.client.session().connected, true, "connected");
    clock += 61 * 1000;
    assert.equal(h.client.session().expired, true, "SESSION_EXPIRED_FLAG");
    const result = await h.client.listQuoteFiles();
    assert.equal(result.code, "drive_token_expired", "TOKEN_EXPIRED_SURFACED");
    assert.equal(h.client.session().connected, false, "EXPIRED_SESSION_CLEARED");
  }

  /* ── 14. Drive API 401 응답도 만료로 처리한다 ── */
  {
    const h = harness({ files: [] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    h.state.uploadQueue = [{ status: 401, data: { error: { message: "unauthorized" } } }];
    const result = await h.client.uploadFile({ name: "a.json", mimeType: JSON_MIME, bytes: new Uint8Array(10) });
    assert.equal(result.code, "drive_token_expired", "401_MAPS_TO_TOKEN_EXPIRED");
  }

  /* ── 15. Picker 를 못 쓰는 환경은 명시 코드로 돌아온다 ── */
  {
    const h = harness({ files: [] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const picked = await h.client.openPicker();
    assert.equal(picked.code, "picker_unavailable", "PICKER_UNAVAILABLE_IS_EXPLICIT");
    assert.equal(picked.ok, false, "picker unavailable is not success");
  }

  /* ── 16. 통신 대상은 Google OAuth/Drive 뿐이다(모델 호출 0) ── */
  {
    const draft = draftFixture();
    const text = packageTextFor(draft, "pkg-network");
    const h = harness({
      metadata: { id: "file-n", name: "n.json", mimeType: JSON_MIME, size: Buffer.byteLength(text, "utf8"), trashed: false, owners: [{ me: true }] },
      media: text,
      uploads: [
        { data: { id: "j", name: "a.json" } },
        { data: { id: "p", name: "a.pdf" } }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    await h.client.savePair({ draft, pdfBytes: pdfBytes() });
    await h.client.openQuoteFile("file-n");
    assert.ok(h.calls.length > 0, "calls recorded");
    h.calls.forEach((call) => {
      const host = call.url.replace(/^https?:\/\//, "").split("/")[0];
      assert.ok(
        host === "www.googleapis.com" || host === "oauth2.googleapis.com",
        "ONLY_GOOGLE_ENDPOINTS: " + host
      );
    });
    const modelish = h.calls.filter((call) => /model|llm|chat|completion|interpret/i.test(call.url));
    assert.equal(modelish.length, 0, "MODEL_CALLS_FOR_STORAGE=0");
  }

  console.log("B66_DRIVE_CLIENT=PASS");
  console.log("LEAST_SCOPE_REQUESTED=drive.file");
  console.log("MANUAL_JSON_PDF_PAIR_SAVE=PASS");
  console.log("DUPLICATE_NAME_NO_OVERWRITE=PASS");
  console.log("PARTIAL_UPLOAD_REPORTED_AND_RECOVERABLE=PASS");
  console.log("NO_ORPHAN_UPLOAD_ON_INVALID_PDF=PASS");
  console.log("REOPEN_RECALCULATED_BY_QUOTECORE=PASS");
  console.log("OTHER_GOOGLE_ACCOUNT_ACCESS=DENIED");
  console.log("LOGOUT_BLOCKS_ACCESS=PASS");
  console.log("TOKEN_EXPIRED_SURFACED=PASS");
  console.log("ONLY_GOOGLE_ENDPOINTS=PASS");
  console.log("MODEL_CALLS_FOR_STORAGE=0");
  console.log("SLICE_B_OFFLINE_TESTED=PASS");
  console.log("SLICE_C_OFFLINE_TESTED=PASS");
})().catch((error) => {
  console.error("B66_DRIVE_CLIENT=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
