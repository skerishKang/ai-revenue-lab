/* #3871 Slice B/C — Google Drive 연결·저장·불러오기 오프라인 테스트.
   실제 Google 계정·네트워크·모델 호출은 사용하지 않는다. 모든 통신은 주입된 스텁이다. */
const assert = require("node:assert");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");

const CLIENT_ID = "test-client-id.apps.googleusercontent.com";
const JSON_MIME = Contract.JSON_MIME;
const PDF_MIME = Contract.PDF_MIME;
const SKILL_ID = "b66skill_2eb55d822407f626b7a75c8c88d32c40";
const TEMPLATE = { savedSkillId: SKILL_ID, fingerprint: "fp-cgi-v1" };
const APPROVED = [{ savedSkillId: SKILL_ID, fingerprint: "fp-cgi-v1", approved: true, active: true }];

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

function pdfBytes(marker) {
  const bytes = new Uint8Array(512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  if (marker) bytes[400] = marker;
  return bytes;
}

function packageTextFor(draft, packageId, template) {
  const built = Contract.buildPackage({
    draft,
    template: template === undefined ? TEMPLATE : template,
    savedAt: "2026-10-09T09:00:00.000Z",
    packageId: packageId || "pkg-client-0001"
  });
  return Contract.serializePackage(built.package);
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const uploadCalls = (h) => h.calls.filter((call) => call.url.indexOf("/upload/drive") !== -1);

/* ── 스텁 하네스 ── */
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

  function parseQuery(target) {
    const queryIndex = target.indexOf("?");
    const params = {};
    if (queryIndex === -1) return params;
    target.slice(queryIndex + 1).split("&").forEach((pair) => {
      if (!pair) return;
      const eq = pair.indexOf("=");
      const key = eq === -1 ? pair : pair.slice(0, eq);
      const value = eq === -1 ? "" : pair.slice(eq + 1);
      params[decodeURIComponent(key)] = decodeURIComponent(value);
    });
    return params;
  }

  const fetchImpl = async (url, init) => {
    const target = String(url);
    calls.push({ url: target, method: (init && init.method) || "GET" });
    const request = init || {};
    if (typeof state.beforeResponse === "function") await state.beforeResponse(target);

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
      if (next.status && next.status >= 400) {
        return jsonResponse(next.data || { error: { message: "stub failure" } }, next.status);
      }
      const id = "id-" + (state.created.length + 1);
      state.created.push({ id, name, mimeType: next.mimeType || "" });
      state.files.push({ id, name, mimeType: next.mimeType || "", trashed: false, owners: [{ me: true }] });
      return jsonResponse({ id, name }, next.status);
    }

    if (target.indexOf("alt=media") !== -1) {
      return { ok: true, status: 200, headers: { get: () => null }, text: async () => String(state.media || "") };
    }

    if (target.indexOf("/drive/v3/files/") !== -1) {
      const rest = target.slice(target.indexOf("/drive/v3/files/") + "/drive/v3/files/".length);
      const id = decodeURIComponent(rest.split("?")[0]);
      const meta = state.metadataById[id];
      if (!meta) return jsonResponse({ error: { message: "not found" } }, 404);
      if (meta.status && meta.status >= 400) return jsonResponse({ error: { message: "denied" } }, meta.status);
      return jsonResponse(meta);
    }

    if (target.indexOf("/drive/v3/files?") !== -1) {
      if (state.listStatus >= 400) return jsonResponse({ error: { message: "list failed" } }, state.listStatus);
      const params = parseQuery(target);
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
      const hasMore = nextOffset < state.files.length;
      const body = { files: slice };
      if (hasMore || state.forcePageToken) body.nextPageToken = String(nextOffset);
      return jsonResponse(body);
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
    appId: opts.appId || "",
    developerKey: opts.developerKey || "",
    fetch: fetchImpl,
    google: google,
    gapi: null,
    now: opts.now || (() => Date.now()),
    loadScript: async () => { throw new Error("no network in test"); }
  });

  return {
    client, calls, state, google,
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

(async () => {
  /* ── 1. 설정 없이는 실패(명시 코드) ── */
  {
    const h = harness({ clientId: "" });
    const result = await h.client.connect();
    assert.equal(result.code, "drive_not_configured", "DRIVE_NOT_CONFIGURED");
    assert.equal(h.client.isConfigured(), false, "isConfigured false");
    assert.equal(h.client.pickerReady(), false, "PICKER_NOT_READY_WITHOUT_CONFIG");
  }

  /* ── 2. 연결 성공: 최소 권한 drive.file 만 요청 ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await flush();
    assert.equal(h.state.lastScope, Client.SCOPE_DRIVE_FILE, "LEAST_SCOPE_REQUESTED=drive.file");
    assert.equal(h.state.lastScope.indexOf("drive.readonly"), -1, "NO_BLANKET_DRIVE_SCOPE");
    await h.approve();
    const result = await pending;
    assert.deepEqual(result.scopes, [Client.SCOPE_DRIVE_FILE], "GRANTED_SCOPE=drive.file");
    assert.equal(h.client.session().connected, true, "SESSION_CONNECTED");
  }

  /* ── 3. 동의 취소/실패 ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await h.deny("popup_closed");
    const result = await pending;
    assert.equal(result.code, "drive_auth_denied", "DRIVE_AUTH_DENIED");
    assert.equal(h.client.session().connected, false, "DENIED_LEAVES_NO_SESSION");
    assert.equal((await h.client.listQuoteFiles()).code, "drive_not_connected", "DENIED_THEN_NOT_CONNECTED");
  }

  /* ── 4. JSON + PDF 한 쌍 저장 ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft: draftFixture(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "SAVE_PAIR_COMPLETE");
    assert.equal(outcome.json.id, "id-1", "JSON_FILE_ID");
    assert.equal(outcome.pdf.id, "id-2", "PDF_FILE_ID");
    assert.equal(uploadCalls(h).length, 2, "TWO_UPLOADS");
    assert.equal(uploadCalls(h)[0].method, "POST", "UPLOAD_IS_CREATE_NOT_UPDATE");
    assert.ok(outcome.pair && outcome.pair.draftFingerprint && outcome.pair.pdfFingerprint, "PAIR_BINDING_PRESENT");
    assert.ok(outcome.pair.jsonName.endsWith(".json"), "PAIR_JSON_NAME");
    assert.ok(outcome.pair.pdfName.endsWith(".pdf"), "PAIR_PDF_NAME");
  }

  /* ── 5. 같은 이름이 있으면 덮어쓰지 않고 접미사 ── */
  {
    const base = Contract.buildBaseName(draftFixture());
    const h = harness({
      files: [{ id: "old", name: base + ".json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft: draftFixture(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "duplicate handled");
    assert.equal(outcome.renamed, true, "DUPLICATE_RENAMED");
    assert.notEqual(outcome.json.name, base + ".json", "EXISTING_FILE_NOT_OVERWRITTEN");
  }

  /* ── 6. 저장 직전 이름 재확인(그 사이 생성된 파일) ── */
  {
    const base = Contract.buildBaseName(draftFixture());
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    h.state.beforeResponse = async (target) => {
      if (target.indexOf("/drive/v3/files?") === -1) return;
      if (target.indexOf("name%20%3D") === -1) return;
      if (target.indexOf(encodeURIComponent(base + ".json")) !== -1 &&
          !h.state.files.some((file) => file.name === base + ".json")) {
        h.state.files.push({ id: "race", name: base + ".json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] });
      }
    };
    const outcome = await h.client.savePair({ draft: draftFixture(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "complete", "RACE_SAVE_COMPLETES");
    assert.notEqual(outcome.json.name, base + ".json", "RACE_NAME_REPLANNED");
  }

  /* ── 7. 이름 점검 실패/잘림은 fail-closed ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    h.state.listStatus = 500;
    const outcome = await h.client.savePair({ draft: draftFixture(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "failed", "NAMING_CHECK_FAILURE_DENIES_SAVE");
    assert.equal(outcome.code, "naming_check_unavailable", "NAMING_CHECK_UNAVAILABLE");
    assert.equal(uploadCalls(h).length, 0, "NO_UPLOAD_WITHOUT_NAMING_CHECK");
  }
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    h.state.forcePageToken = true;
    const outcome = await h.client.savePair({ draft: draftFixture(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.code, "naming_check_incomplete", "TRUNCATED_NAMING_CHECK_DENIES_SAVE");
    assert.equal(uploadCalls(h).length, 0, "NO_UPLOAD_ON_TRUNCATED_LIST");
  }

  /* ── 8. 부분 실패 → 원래 쌍을 유지한 채 재시도 ── */
  {
    const draft = draftFixture();
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "storage quota exceeded" } } },
        { mimeType: PDF_MIME }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "partial_json", "PARTIAL_JSON_REPORTED");
    assert.equal(outcome.reported, true, "PARTIAL_REPORTED_NOT_SILENT");
    assert.equal(outcome.ok, false, "PARTIAL_IS_NOT_SUCCESS");
    const frozenJsonName = outcome.pair.jsonName;
    h.state.metadataById[outcome.json.id] = {
      id: outcome.json.id, name: frozenJsonName, mimeType: JSON_MIME, size: 4000,
      trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
    };

    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.status, "complete", "RETRY_COMPLETES");
    assert.equal(retried.json.name, frozenJsonName, "RETRY_REUSES_FROZEN_JSON_NAME");
    assert.equal(retried.pdf.name, outcome.pair.pdfName, "RETRY_REUSES_FROZEN_PDF_NAME");
    assert.equal(retried.json.id, outcome.json.id, "RETRY_KEEPS_ORIGINAL_JSON_FILE");
    assert.equal(uploadCalls(h).length, 3, "RETRY_UPLOADS_ONLY_MISSING_SIDE");
  }

  /* ── 9. 수정된 견적은 이어서 저장하지 않는다 ── */
  {
    const draft = draftFixture();
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(outcome.status, "partial_json", "partial");
    h.state.metadataById[outcome.json.id] = {
      id: outcome.json.id, name: outcome.pair.jsonName, mimeType: JSON_MIME, size: 4000,
      trashed: false, owners: [{ me: true }]
    };
    const edited = Core.normalizeDraft(Object.assign({}, draft, {
      items: [{ id: "item-1", name: "서비스 구축", qty: 9, unitPrice: 1000000 }]
    }));
    const before = uploadCalls(h).length;
    const retried = await h.client.retryMissing({ outcome, draft: edited, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.ok, false, "EDITED_DRAFT_RETRY_BLOCKED");
    assert.equal(retried.code, "pending_pair_stale", "PENDING_PAIR_STALE");
    assert.equal(uploadCalls(h).length, before, "NO_UPLOAD_ON_STALE_PAIR");
  }

  /* ── 10. 유지된 파일이 사라졌으면 완료를 주장하지 않는다 ── */
  {
    const draft = draftFixture();
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.code, "kept_file_unavailable", "MISSING_KEPT_FILE_BLOCKS_RETRY");
    assert.equal(retried.detail, "drive_file_not_found", "KEPT_FILE_DETAIL");
    assert.equal(uploadCalls(h).length, 2, "NO_UPLOAD_WITHOUT_KEPT_FILE");
  }

  /* ── 11. 재시도 시 고정 이름이 이미 점유되면 새 저장을 요구한다 ── */
  {
    const draft = draftFixture();
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    h.state.metadataById[outcome.json.id] = {
      id: outcome.json.id, name: outcome.pair.jsonName, mimeType: JSON_MIME, size: 4000,
      trashed: false, owners: [{ me: true }]
    };
    h.state.files.push({ id: "squatter", name: outcome.pair.pdfName, mimeType: PDF_MIME, trashed: false, owners: [{ me: true }] });
    const retried = await h.client.retryMissing({ outcome, draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(retried.code, "duplicate_name_conflict", "FROZEN_NAME_TAKEN_BLOCKS_RETRY");
    assert.equal(uploadCalls(h).length, 2, "NO_UPLOAD_ON_NAME_CONFLICT");
  }

  /* ── 12. PDF 바이트가 잘못되면 아무것도 올리지 않는다 ── */
  {
    const h = harness({ uploads: [] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const outcome = await h.client.savePair({ draft: draftFixture(), template: TEMPLATE, pdfBytes: null });
    assert.equal(outcome.code, "pdf_missing", "PDF_MISSING_CODE");
    assert.equal(uploadCalls(h).length, 0, "NO_ORPHAN_UPLOAD");
  }

  /* ── 13. 소유 정보가 없거나 비어 있으면 거부(fail-closed) ── */
  {
    const draft = draftFixture();
    const text = packageTextFor(draft, "pkg-own", TEMPLATE);
    const h = harness({ media: text });
    const pending = h.client.connect();
    await h.approve();
    await pending;

    h.state.metadataById.owned = {
      id: "owned", name: "a.json", mimeType: JSON_MIME, size: 4000, trashed: false,
      owners: [{ me: true }], capabilities: { canDownload: true }
    };
    const okOpen = await h.client.openQuoteFile("owned", { templates: APPROVED });
    assert.equal(okOpen.ok, true, "OWNED_FILE_OPENS");

    const mediaCount = () => h.calls.filter((call) => call.url.indexOf("alt=media") !== -1).length;
    const mediaBefore = mediaCount();

    h.state.metadataById.noOwners = {
      id: "noOwners", name: "b.json", mimeType: JSON_MIME, size: 4000, trashed: false,
      capabilities: { canDownload: true }
    };
    const missingOwners = await h.client.openQuoteFile("noOwners", { templates: APPROVED });
    assert.equal(missingOwners.ok, false, "MISSING_OWNERS_DENIED");
    assert.equal(missingOwners.code, "drive_file_ownership_unverified", "MISSING_OWNERS_CODE");
    assert.equal(mediaCount(), mediaBefore, "NO_MEDIA_FETCH_WITHOUT_OWNER");

    h.state.metadataById.emptyOwners = {
      id: "emptyOwners", name: "c.json", mimeType: JSON_MIME, size: 4000, trashed: false,
      owners: [], capabilities: { canDownload: true }
    };
    const emptyOwners = await h.client.openQuoteFile("emptyOwners", { templates: APPROVED });
    assert.equal(emptyOwners.code, "drive_file_ownership_unverified", "EMPTY_OWNERS_DENIED");
    assert.equal(mediaCount(), mediaBefore, "NO_MEDIA_FETCH_WITH_EMPTY_OWNERS");

    h.state.metadataById.foreign = {
      id: "foreign", name: "d.json", mimeType: JSON_MIME, size: 4000, trashed: false,
      owners: [{ me: false, emailAddress: "other@example.com" }], capabilities: { canDownload: true }
    };
    const foreign = await h.client.openQuoteFile("foreign", { templates: APPROVED });
    assert.equal(foreign.code, "drive_file_not_owned_by_connected_account", "OTHER_ACCOUNT_DENIED");
    assert.equal(mediaCount(), mediaBefore, "NO_MEDIA_FETCH_FOR_FOREIGN_OWNER");

    h.state.metadataById.notDownloadable = {
      id: "notDownloadable", name: "e.json", mimeType: JSON_MIME, size: 4000, trashed: false,
      owners: [{ me: true }], capabilities: { canDownload: false }
    };
    const notDownloadable = await h.client.openQuoteFile("notDownloadable", { templates: APPROVED });
    assert.equal(notDownloadable.code, "drive_file_not_downloadable", "NOT_DOWNLOADABLE_DENIED");

    h.state.metadataById.trashed = {
      id: "trashed", name: "f.json", mimeType: JSON_MIME, size: 4000, trashed: true,
      owners: [{ me: true }], capabilities: { canDownload: true }
    };
    const trashed = await h.client.openQuoteFile("trashed", { templates: APPROVED });
    assert.equal(trashed.code, "drive_file_trashed", "TRASHED_FILE_REJECTED");
  }

  /* ── 14. 목록은 소유가 확인된 파일만 돌려준다 ── */
  {
    const h = harness({
      files: [
        { id: "a", name: "mine.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] },
        { id: "b", name: "not-mine.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: false }] },
        { id: "c", name: "no-owners.json", mimeType: JSON_MIME, trashed: false },
        { id: "d", name: "empty-owners.json", mimeType: JSON_MIME, trashed: false, owners: [] },
        { id: "e", name: "gone.json", mimeType: JSON_MIME, trashed: true, owners: [{ me: true }] }
      ]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const list = await h.client.listQuoteFiles();
    assert.deepEqual(list.files.map((file) => file.id), ["a"], "LIST_ONLY_VERIFIED_OWNED_FILES");
    assert.equal(list.withheld, 4, "UNVERIFIED_FILES_WITHHELD");
  }

  /* ── 15. 목록 페이지 처리 ── */
  {
    const files = [];
    for (let index = 0; index < 7; index += 1) {
      files.push({
        id: "p" + index, name: "q" + index + ".json", mimeType: JSON_MIME,
        trashed: false, owners: [{ me: true }]
      });
    }
    const h = harness({ files: files });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const list = await h.client.listQuoteFiles({ pageSize: 3 });
    assert.equal(list.ok, true, "PAGINATED_LIST_OK");
    assert.equal(list.files.length, 7, "ALL_PAGES_COLLECTED");
    assert.equal(list.pages, 3, "THREE_PAGES");
    assert.equal(list.truncated, false, "NOT_TRUNCATED_WHEN_EXHAUSTED");

    h.state.forcePageToken = true;
    const truncated = await h.client.listQuoteFiles({ pageSize: 3, maxPages: 2 });
    assert.equal(truncated.truncated, true, "TRUNCATED_FLAG_SET");
    assert.equal(truncated.pages, 2, "MAX_PAGES_BOUNDED");
  }

  /* ── 16. 다시 열기: 소유 검증 + QuoteCore 재계산 + 템플릿 권위 ── */
  {
    const draft = draftFixture();
    const text = packageTextFor(draft, "pkg-open", TEMPLATE);
    const h = harness({
      metadataById: {
        "file-1": {
          id: "file-1", name: "견적서_PQ-20261009-002_가나상사.json", mimeType: JSON_MIME,
          size: Buffer.byteLength(text, "utf8"), trashed: false,
          owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: text
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const opened = await h.client.openQuoteFile("file-1", { templates: APPROVED });
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
    assert.equal(opened.contentFingerprint, Contract.contentFingerprint(draft, TEMPLATE), "CONTENT_FINGERPRINT_RETURNED");
  }

  /* ── 17. 템플릿 권위가 확인되지 않으면 편집기용 draft 를 주지 않는다 ── */
  {
    const draft = draftFixture();
    const text = packageTextFor(draft, "pkg-template", TEMPLATE);
    const h = harness({
      metadataById: {
        "file-2": {
          id: "file-2", name: "t.json", mimeType: JSON_MIME, size: Buffer.byteLength(text, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: text
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const unresolved = await h.client.openQuoteFile("file-2", { templates: [] });
    assert.equal(unresolved.ok, false, "UNRESOLVED_TEMPLATE_BLOCKS_OPEN");
    assert.equal(unresolved.code, "saved_skill_unavailable", "UNRESOLVED_TEMPLATE_CODE");
    assert.equal(unresolved.draft, undefined, "NO_DRAFT_FOR_UNRESOLVED_TEMPLATE");

    const inactive = await h.client.openQuoteFile("file-2", {
      templates: [{ savedSkillId: SKILL_ID, fingerprint: "fp-cgi-v1", approved: false, active: true }]
    });
    assert.equal(inactive.code, "saved_skill_inactive", "INACTIVE_TEMPLATE_BLOCKS_OPEN");

    const mismatched = await h.client.openQuoteFile("file-2", {
      templates: [{ savedSkillId: SKILL_ID, fingerprint: "other", approved: true, active: true }]
    });
    assert.equal(mismatched.code, "template_fingerprint_mismatch", "MISMATCHED_TEMPLATE_BLOCKS_OPEN");
  }

  /* ── 18. 변조된 본문은 다시 열기에서도 거부된다 ── */
  {
    const draft = draftFixture();
    const raw = JSON.parse(packageTextFor(draft, "pkg-tamper", TEMPLATE));
    raw.quote.items[0].unitPrice = 1;
    const text = JSON.stringify(raw);
    const h = harness({
      metadataById: {
        "file-3": {
          id: "file-3", name: "t.json", mimeType: JSON_MIME, size: Buffer.byteLength(text, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: text
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const opened = await h.client.openQuoteFile("file-3", { templates: APPROVED });
    assert.equal(opened.ok, false, "TAMPERED_BODY_REJECTED_ON_OPEN");
    assert.equal(opened.code, "content_fingerprint_mismatch", "TAMPER_CODE");
  }

  /* ── 19. 저장된 합계 변조는 무시되고 재계산된다 ── */
  {
    const draft = draftFixture();
    const raw = JSON.parse(packageTextFor(draft, "pkg-totals", TEMPLATE));
    raw.totals = { supply: 7, vat: 7, grand: 7 };
    const text = JSON.stringify(raw);
    const h = harness({
      metadataById: {
        "file-4": {
          id: "file-4", name: "t.json", mimeType: JSON_MIME, size: Buffer.byteLength(text, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: text
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const opened = await h.client.openQuoteFile("file-4", { templates: APPROVED });
    assert.equal(opened.ok, true, "tampered totals file opens");
    assert.equal(opened.totalsIgnored, true, "STORED_TOTALS_IGNORED_ON_REOPEN");
    const expected = Core.computeDraftTotals(draft);
    assert.equal(opened.totals.grand, expected.grand, "TAMPERED_TOTALS_RECALCULATED");
    assert.notEqual(opened.totals.grand, 7, "변조값 미반영");
  }

  /* ── 20. 로그아웃 후 권한 차단 + 계정 전환 ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const out = await h.client.disconnect();
    assert.equal(out.revoked, true, "TOKEN_REVOKED_ON_LOGOUT");
    assert.equal(h.client.session().connected, false, "LOGOUT_CLEARS_SESSION");
    assert.equal((await h.client.openQuoteFile("file-1")).code, "drive_not_connected", "LOGOUT_BLOCKS_OPEN");
    assert.equal((await h.client.savePair({ draft: draftFixture(), pdfBytes: pdfBytes() })).code,
      "drive_not_connected", "LOGOUT_BLOCKS_SAVE");
    assert.equal(uploadCalls(h).length, 0, "NO_UPLOAD_AFTER_LOGOUT");

    const second = h.client.connect({ prompt: "select_account" });
    await flush();
    assert.equal(h.state.lastPrompt, "select_account", "ACCOUNT_SWITCH_PROMPT");
    await h.approve();
    await second;
    assert.equal(h.client.session().connected, true, "SWITCHED_ACCOUNT_CONNECTED");
  }

  /* ── 21. 계정 전환 뒤 도착한 in-flight 응답은 반영되지 않는다 ── */
  {
    const h = harness({
      files: [{ id: "a", name: "mine.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    let release = null;
    h.state.beforeResponse = (target) => {
      if (target.indexOf("/drive/v3/files?") === -1) return undefined;
      return new Promise((resolve) => { release = resolve; });
    };
    const listing = h.client.listQuoteFiles();
    await flush();
    await h.client.disconnect({ reason: "b66_account_authority_changed" });
    release();
    const result = await listing;
    assert.equal(result.ok, false, "IN_FLIGHT_RESPONSE_DISCARDED");
    assert.equal(result.code, "drive_session_changed", "SESSION_EPOCH_GUARD");
    assert.deepEqual(result.files, [], "NO_FILES_LEAKED_ACROSS_ACCOUNT");
  }

  /* ── 22. 토큰 만료 ── */
  {
    let clock = 1000000;
    const h = harness({ files: [], now: () => clock });
    const pending = h.client.connect();
    await h.approve({ expires_in: 60 });
    await pending;
    clock += 61 * 1000;
    assert.equal(h.client.session().expired, true, "SESSION_EXPIRED_FLAG");
    const result = await h.client.listQuoteFiles();
    assert.equal(result.code, "drive_token_expired", "TOKEN_EXPIRED_SURFACED");
    assert.equal(h.client.session().connected, false, "EXPIRED_SESSION_CLEARED");
  }

  /* ── 23. Drive 401 은 만료로 처리 ── */
  {
    const h = harness({ uploads: [{ status: 401, data: { error: { message: "unauthorized" } } }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const result = await h.client.uploadFile({ name: "a.json", mimeType: JSON_MIME, bytes: new Uint8Array(10) });
    assert.equal(result.code, "drive_token_expired", "401_MAPS_TO_TOKEN_EXPIRED");
  }

  /* ── 24. Picker 설정 없음 ── */
  {
    const h = harness({ files: [] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    assert.equal(h.client.pickerReady(), false, "PICKER_NOT_READY_WITHOUT_APP_ID");
    const picked = await h.client.openPicker();
    assert.equal(picked.code, "picker_unavailable", "PICKER_UNAVAILABLE_IS_EXPLICIT");
  }

  /* ── 25. 연결이 진행 중이면 중복 시작을 거부한다 ── */
  {
    const h = harness();
    const first = h.client.connect();
    await flush();
    assert.equal(h.client.session().connectPending, true, "CONNECT_PENDING_FLAG");
    const second = await h.client.connect();
    assert.equal(second.ok, false, "SECOND_CONNECT_REFUSED");
    assert.equal(second.code, "drive_connect_in_progress", "CONNECT_IN_PROGRESS_CODE");
    await h.approve();
    const result = await first;
    assert.equal(result.ok, true, "FIRST_CONNECT_SUCCEEDS");
    assert.equal(h.client.session().connectPending, false, "CONNECT_PENDING_CLEARED");
  }

  /* ── 26. OAuth 팝업 도중 B66 로그아웃 → 뒤늦은 토큰을 받지 않는다(보안) ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await flush();
    assert.equal(h.client.session().connectPending, true, "POPUP_PENDING");
    /* 팝업이 떠 있는 동안 B66 로그아웃/계정 전환 */
    await h.client.disconnect({ reason: "b66_signed_out" });
    await h.approve();
    const result = await pending;
    assert.equal(result.ok, false, "LATE_TOKEN_NOT_ACCEPTED");
    assert.equal(result.code, "drive_auth_superseded", "DRIVE_AUTH_SUPERSEDED");
    assert.equal(h.client.session().connected, false, "NO_SESSION_AFTER_LATE_TOKEN");
    const revoked = h.calls.filter((call) => call.url.indexOf("oauth2.googleapis.com/revoke") !== -1);
    assert.equal(revoked.length, 1, "LATE_TOKEN_REVOKED");
    assert.ok(revoked[0].url.indexOf("stub-access-token") !== -1, "REVOKE_TARGETS_LATE_TOKEN");
    assert.equal((await h.client.listQuoteFiles()).code, "drive_not_connected", "STILL_SIGNED_OUT");
  }

  /* ── 27. 팝업 도중 계정 전환 후에도 연결이 만들어지지 않는다 ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await flush();
    await h.client.disconnect({ reason: "b66_account_changed" });
    await h.approve();
    const result = await pending;
    assert.equal(result.code, "drive_auth_superseded", "SWITCH_SUPERSEDES_CONNECT");
    assert.equal(h.client.session().connected, false, "NO_SESSION_AFTER_SWITCH");
  }

  /* ── 28. 통신 대상은 Google 뿐이다(모델 호출 0) ── */
  {
    const draft = draftFixture();
    const text = packageTextFor(draft, "pkg-network", TEMPLATE);
    const h = harness({
      metadataById: {
        "file-n": {
          id: "file-n", name: "n.json", mimeType: JSON_MIME, size: Buffer.byteLength(text, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: text,
      uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }]
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    await h.client.savePair({ draft, template: TEMPLATE, pdfBytes: pdfBytes() });
    await h.client.openQuoteFile("file-n", { templates: APPROVED });
    assert.ok(h.calls.length > 0, "calls recorded");
    h.calls.forEach((call) => {
      const host = call.url.replace(/^https?:\/\//, "").split("/")[0];
      assert.ok(host === "www.googleapis.com" || host === "oauth2.googleapis.com", "ONLY_GOOGLE_ENDPOINTS: " + host);
    });
    const modelish = h.calls.filter((call) => /model|llm|chat|completion|interpret/i.test(call.url));
    assert.equal(modelish.length, 0, "MODEL_CALLS_FOR_STORAGE=0");
  }

  console.log("B66_DRIVE_CLIENT=PASS");
  console.log("LEAST_SCOPE_REQUESTED=drive.file");
  console.log("MANUAL_JSON_PDF_PAIR_SAVE=PASS");
  console.log("DUPLICATE_NAME_NO_OVERWRITE=PASS");
  console.log("NAMING_CHECK_FAILS_CLOSED=PASS");
  console.log("LIST_PAGINATION_HANDLED=PASS");
  console.log("OWNERSHIP_FAIL_CLOSED=PASS");
  console.log("MISSING_OR_EMPTY_OWNERS_DENIED=PASS");
  console.log("PARTIAL_UPLOAD_REPORTED_AND_RECOVERABLE=PASS");
  console.log("RETRY_PRESERVES_ORIGINAL_PAIR=PASS");
  console.log("EDITED_DRAFT_BLOCKS_RETRY=PASS");
  console.log("NO_ORPHAN_UPLOAD_ON_INVALID_PDF=PASS");
  console.log("REOPEN_RECALCULATED_BY_QUOTECORE=PASS");
  console.log("TEMPLATE_AUTHORITY_REQUIRED_ON_OPEN=PASS");
  console.log("OTHER_GOOGLE_ACCOUNT_ACCESS=DENIED");
  console.log("LOGOUT_BLOCKS_ACCESS=PASS");
  console.log("ACCOUNT_SWITCH_DISCARDS_IN_FLIGHT=PASS");
  console.log("CONNECT_IN_PROGRESS_GUARD=PASS");
  console.log("LATE_TOKEN_AFTER_LOGOUT_REJECTED=PASS");
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
