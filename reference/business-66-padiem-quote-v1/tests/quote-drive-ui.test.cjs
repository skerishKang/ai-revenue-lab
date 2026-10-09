/* #3871 Slice D — 화면 연결 동작 테스트(문서 스텁 주입, 네트워크 없음). */
const assert = require("node:assert");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");
const Ui = require("../quote-drive-ui.js");

const JSON_MIME = Contract.JSON_MIME;
const CLIENT_ID = "test-client-id.apps.googleusercontent.com";

function stubDocument() {
  const registry = new Map();
  function makeNode(tag) {
    return {
      tagName: tag,
      id: "",
      children: [],
      listeners: {},
      className: "",
      type: "",
      hidden: false,
      disabled: false,
      textContent: "",
      value: "",
      dataset: {},
      appendChild(child) { this.children.push(child); return child; },
      replaceChildren() { this.children = Array.prototype.slice.call(arguments); },
      addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); },
      click() { (this.listeners.click || []).slice().forEach((handler) => handler()); }
    };
  }
  const container = makeNode("div");
  container.id = Ui.DEFAULT_CONTAINER_ID;
  registry.set(Ui.DEFAULT_CONTAINER_ID, container);
  return {
    container: container,
    createElement: makeNode,
    getElementById: (id) => registry.get(id) || null
  };
}

function draftFixture() {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: "PQ-20261009-011", issueDate: "2026-10-09", validDays: 30, source: "manual" },
    sender: { company: "공급상사", rep: "김대표", bizNo: "123-45-67890", address: "서울", phone: "02-000-0000", email: "s@example.com", presetId: "custom" },
    recipient: { company: "가나상사", person: "박담당", address: "부산", email: "b@example.com" },
    items: [{ id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: ""
  });
}

function pdfBytes() {
  const bytes = new Uint8Array(512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  return bytes;
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 12; i += 1) await flush(); };

function harness(options) {
  const opts = options || {};
  const doc = stubDocument();
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
      state.created.push({ id: id, name: name, mimeType: next.mimeType || "" });
      state.files.push({ id: id, name: name, mimeType: next.mimeType || "", trashed: false, owners: [{ me: true }] });
      return jsonResponse({ id: id, name: name }, next.status);
    }
    if (target.indexOf("alt=media") !== -1) {
      return { ok: true, status: 200, headers: { get: () => null }, text: async () => String(state.media || "") };
    }
    if (target.indexOf("/drive/v3/files/") !== -1) {
      if (state.metadata === null) return jsonResponse({ error: { message: "not found" } }, 404);
      return jsonResponse(state.metadata, 200);
    }
    if (target.indexOf("/drive/v3/files?") !== -1) return jsonResponse({ files: state.files }, 200);
    return jsonResponse({ error: { message: "unexpected" } }, 404);
  };
  let tokenCallback = null;
  const google = {
    accounts: {
      oauth2: {
        initTokenClient(config) { tokenCallback = config.callback; return { requestAccessToken() {} }; }
      }
    }
  };
  const client = Client.create({
    clientId: opts.clientId === undefined ? CLIENT_ID : opts.clientId,
    fetch: fetchImpl,
    google: google,
    gapi: null,
    loadScript: async () => { throw new Error("no network in test"); }
  });
  const bridgeCalls = [];
  const bridge = {
    getDraft: () => { bridgeCalls.push("getDraft"); return opts.draft || draftFixture(); },
    replaceDraft: (draft) => { bridgeCalls.push("replaceDraft"); bridgeCalls.push(draft); },
    certifiedPdfBytes: async () => (opts.pdfOk === false
      ? { ok: false, code: "pdf_source_unavailable" }
      : { ok: true, bytes: pdfBytes(), fileName: "a.pdf" }),
    activeTemplateReference: () => ({ savedSkillId: "b66skill_x", fingerprint: "fp", approved: true }),
    toast: () => {}
  };
  return {
    doc, client, state, bridgeCalls, bridge,
    async connect() {
      const pending = client.connect();
      await flush();
      tokenCallback({ access_token: "stub-token", expires_in: 3600, scope: Client.SCOPE_DRIVE_FILE });
      await pending;
    },
    mount(extra) {
      return Ui.mount(Object.assign({ document: doc, client: client, bridge: bridge, confirm: () => true }, extra || {}));
    }
  };
}

(async () => {
  /* 1. 컨테이너가 없으면 조용히 실패(기존 화면을 깨지 않는다) */
  {
    const h = harness();
    const mounted = Ui.mount({
      document: { getElementById: () => null, createElement: () => ({ appendChild() {}, addEventListener() {}, replaceChildren() {} }) },
      client: h.client
    });
    assert.equal(mounted.ok, false, "container missing fails closed");
    assert.equal(mounted.code, "container_missing", "CONTAINER_MISSING_CODE");
  }

  /* 2. 연결 설정이 없으면 저장/불러오기 버튼이 막히고 기존 기능은 그대로다 */
  {
    const h = harness({ clientId: "" });
    const ui = h.mount();
    assert.equal(ui.ok, true, "mount ok");
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_WITHOUT_CONFIG");
    assert.equal(ui.openDisabled(), true, "OPEN_DISABLED_WITHOUT_CONFIG");
    assert.ok(ui.statusText().indexOf("준비되지 않았습니다") !== -1, "설정 미준비 안내");
    assert.ok(ui.statusText().indexOf("PDF 다운로드") !== -1, "기존 기능 유지 안내");
    assert.equal(h.bridgeCalls.length, 0, "연결 없이 견적을 읽거나 바꾸지 않는다");
  }

  /* 3. 연결 후 정상 저장 → 성공 메시지 */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: Contract.PDF_MIME }] });
    await h.connect();
    const ui = h.mount();
    assert.equal(ui.session().connected, true, "connected");
    ui.click("save");
    await settle();
    assert.equal(ui.lastOutcome().status, "complete", "UI_SAVE_COMPLETE");
    assert.ok(ui.statusText().indexOf("저장했습니다") !== -1, "SUCCESS_STATUS");
    assert.equal(ui.retryVisible(), false, "완료 시 재시도 버튼 숨김");
    assert.equal(h.state.created.length, 2, "UI_SAVED_TWO_FILES");
  }

  /* 4. 부분 성공은 성공으로 표시되지 않고 재시도 버튼이 나타난다 */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: Contract.PDF_MIME, status: 403, data: { error: { message: "quota" } } },
        { mimeType: Contract.PDF_MIME }
      ]
    });
    await h.connect();
    const ui = h.mount();
    ui.click("save");
    await settle();
    assert.equal(ui.lastOutcome().status, "partial_json", "UI_PARTIAL_STATUS");
    assert.equal(ui.retryVisible(), true, "PARTIAL_RETRY_BUTTON_VISIBLE");
    assert.ok(ui.statusText().indexOf("실패") !== -1, "PARTIAL_MESSAGE_NOT_SILENT");
    ui.click("retry");
    await settle();
    assert.equal(ui.lastOutcome().status, "complete", "UI_RETRY_COMPLETES");
    assert.equal(ui.retryVisible(), false, "RETRY_HIDDEN_AFTER_COMPLETE");
  }

  /* 5. PDF 를 만들지 못하면 업로드를 시작하지 않는다(외톨이 파일 없음) */
  {
    const h = harness({ pdfOk: false, uploads: [{ mimeType: JSON_MIME }] });
    await h.connect();
    const ui = h.mount();
    ui.click("save");
    await settle();
    assert.equal(h.state.created.length, 0, "NO_UPLOAD_WITHOUT_PDF");
    assert.ok(ui.statusText().indexOf("pdf_source_unavailable") !== -1, "PDF 실패 코드 표면화");
  }

  /* 6. 불러오기: 목록 → 선택 → 확인 후 편집기 반영 */
  {
    const draft = draftFixture();
    const pkg = Contract.buildPackage({ draft, packageId: "pkg-ui-1" }).package;
    const media = Contract.serializePackage(pkg);
    const h = harness({
      files: [{ id: "json-1", name: "견적서_PQ-20261009-011_가나상사.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadata: { id: "json-1", name: "a.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"), trashed: false, owners: [{ me: true }] },
      media: media,
      draft: null
    });
    h.bridge.getDraft = () => { h.bridgeCalls.push("getDraft"); return draft; };
    await h.connect();
    const ui = h.mount();
    ui.click("open");
    await settle();
    assert.ok(ui.statusText().indexOf("선택해 주세요") !== -1, "FILE_LIST_PRESENTED");
    ui.click("confirmOpen");
    await settle();
    assert.ok(h.bridgeCalls.indexOf("replaceDraft") !== -1, "DRAFT_APPLIED_TO_EDITOR");
    const applied = h.bridgeCalls[h.bridgeCalls.indexOf("replaceDraft") + 1];
    assert.deepEqual(applied, draft, "LOADED_DRAFT_IDENTICAL");
    assert.ok(ui.statusText().indexOf("다시 계산") !== -1, "RECALCULATION_EXPLAINED");
  }

  /* 7. 사용자가 취소하면 편집 중 견적을 바꾸지 않는다 */
  {
    const draft = draftFixture();
    const media = Contract.serializePackage(Contract.buildPackage({ draft, packageId: "pkg-ui-2" }).package);
    const h = harness({
      files: [{ id: "json-2", name: "b.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadata: { id: "json-2", name: "b.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"), trashed: false, owners: [{ me: true }] },
      media: media
    });
    await h.connect();
    const ui = h.mount({ confirm: () => false });
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.equal(h.bridgeCalls.indexOf("replaceDraft"), -1, "CANCEL_DOES_NOT_REPLACE_DRAFT");
    assert.ok(ui.statusText().indexOf("취소") !== -1, "CANCEL_EXPLAINED");
  }

  /* 8. 연결 해제 후에는 저장/불러오기가 막힌다 */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    await h.connect();
    const ui = h.mount();
    ui.click("connect");
    await settle();
    assert.equal(ui.session().connected, false, "LOGOUT_APPLIED");
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_AFTER_LOGOUT");
    assert.equal(ui.openDisabled(), true, "OPEN_DISABLED_AFTER_LOGOUT");
    assert.ok(ui.statusText().indexOf("해제") !== -1, "LOGOUT_STATUS");
  }

  console.log("B66_DRIVE_UI=PASS");
  console.log("UI_CONTAINER_FAILS_CLOSED=PASS");
  console.log("UI_OPTIONAL_WITHOUT_CONFIG=PASS");
  console.log("UI_SAVE_SUCCESS_STATUS=PASS");
  console.log("UI_PARTIAL_NOT_SILENT=PASS");
  console.log("UI_NO_UPLOAD_WITHOUT_PDF=PASS");
  console.log("UI_OPEN_APPLIES_RECALCULATED_DRAFT=PASS");
  console.log("UI_CANCEL_PRESERVES_CURRENT_DRAFT=PASS");
  console.log("UI_LOGOUT_BLOCKS_ACTIONS=PASS");
  console.log("SLICE_D_OFFLINE_TESTED=PASS");
})().catch((error) => {
  console.error("B66_DRIVE_UI=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
