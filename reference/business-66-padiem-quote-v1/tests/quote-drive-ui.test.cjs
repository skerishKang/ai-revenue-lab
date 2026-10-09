/* #3871 Slice D — 화면 연결 동작 테스트(문서 스텁 주입, 네트워크 없음). */
const assert = require("node:assert");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");
const Ui = require("../quote-drive-ui.js");
const { createEditorBridge } = require("./quote-editor-stub.cjs");

const JSON_MIME = Contract.JSON_MIME;
const PDF_MIME = Contract.PDF_MIME;
const CLIENT_ID = "test-client-id.apps.googleusercontent.com";
const SKILL_ID = "b66skill_2eb55d822407f626b7a75c8c88d32c40";
const TEMPLATE = { savedSkillId: SKILL_ID, fingerprint: "fp-cgi-v1" };
const APPROVED = [{ savedSkillId: SKILL_ID, fingerprint: "fp-cgi-v1", approved: true, active: true, label: "CGI" }];

function stubDocument() {
  const registry = new Map();
  const docHandlers = {};
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
    getElementById: (id) => registry.get(id) || null,
    addEventListener(type, handler) { (docHandlers[type] = docHandlers[type] || []).push(handler); },
    dispatch(type, detail) {
      (docHandlers[type] || []).slice().forEach((handler) => handler({ detail: detail }));
    }
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

function pdfBytes(marker) {
  const bytes = new Uint8Array(512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  if (marker) bytes[300] = marker;
  return bytes;
}

function packageTextFor(draft, packageId) {
  const built = Contract.buildPackage({
    draft,
    template: TEMPLATE,
    savedAt: "2026-10-09T09:00:00.000Z",
    packageId: packageId
  });
  return Contract.serializePackage(built.package);
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let index = 0; index < 25; index += 1) await flush(); };

function harness(options) {
  const opts = options || {};
  const doc = stubDocument();
  const state = {
    files: (opts.files || []).slice(),
    metadataById: opts.metadataById || {},
    media: opts.media === undefined ? null : opts.media,
    uploadQueue: (opts.uploads || []).slice(),
    created: [],
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
      return jsonResponse({ files: state.files });
    }
    return jsonResponse({ error: { message: "unexpected" } }, 404);
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
  /* 실제 클라이언트는 Object.freeze 이므로, 테스트에서 Picker 만 바꿔 끼울 수 있도록
     같은 클로저를 공유하는 얇은 래퍼를 쓴다(세션 상태는 동일하다). */
  const client = Object.assign({}, Client.create({
    clientId: opts.clientId === undefined ? CLIENT_ID : opts.clientId,
    appId: opts.appId || "",
    developerKey: opts.developerKey || "",
    fetch: fetchImpl,
    google: google,
    gapi: null,
    loadScript: async () => { throw new Error("no network in test"); }
  }));

  /* 편집기 + 브리지 스텁은 실제 제품 모듈(quote-import-atomic.js)을 그대로 사용한다. */
  const editorHarness = createEditorBridge({
    draft: opts.draft || draftFixture(),
    activeTemplate: opts.templateRef === undefined ? TEMPLATE : opts.templateRef,
    approvedSkills: opts.approvedSkills === undefined ? APPROVED : opts.approvedSkills,
    hasMeaningfulDraft: opts.hasMeaningfulDraft !== false,
    writeBehavior: opts.writeBehavior,
    restoreFails: opts.restoreFails === true,
    pdfOk: opts.pdfOk,
    pdfBytes: opts.pdfBytes
  });
  const bridge = editorHarness.bridge;
  const current = editorHarness.editor;
  const bridgeCalls = editorHarness.calls;

  return {
    doc, client, state, bridgeCalls, bridge, current,
    editor: editorHarness.editor,
    writes: editorHarness.writes,
    async connect() {
      const pending = client.connect();
      await flush();
      tokenCallback({ access_token: "stub-token", expires_in: 3600, scope: Client.SCOPE_DRIVE_FILE });
      await pending;
    },
    mount(extra) {
      return Ui.mount(Object.assign({
        document: doc, client: client, bridge: bridge, contract: Contract, confirm: () => true
      }, extra || {}));
    }
  };
}

(async () => {
  /* ── 1. 컨테이너가 없으면 조용히 실패 ── */
  {
    const h = harness();
    const mounted = Ui.mount({
      document: { getElementById: () => null, createElement: () => ({ appendChild() {}, addEventListener() {}, replaceChildren() {} }) },
      client: h.client,
      contract: Contract
    });
    assert.equal(mounted.ok, false, "container missing fails closed");
    assert.equal(mounted.code, "container_missing", "CONTAINER_MISSING_CODE");
  }

  /* ── 2. 연결 설정이 없으면 저장/불러오기가 막히고 기존 기능은 그대로 ── */
  {
    const h = harness({ clientId: "" });
    const ui = h.mount();
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_WITHOUT_CONFIG");
    assert.equal(ui.openDisabled(), true, "OPEN_DISABLED_WITHOUT_CONFIG");
    assert.ok(ui.statusText().indexOf("준비되지 않았습니다") !== -1, "설정 미준비 안내");
    assert.ok(ui.statusText().indexOf("PDF 다운로드") !== -1, "기존 기능 유지 안내");
    assert.equal(h.bridgeCalls.length, 0, "연결 없이 견적을 읽거나 바꾸지 않는다");
  }

  /* ── 3. 시작 훅: 브리지가 준비된 뒤 1회만 mount 되고 컨트롤이 실제로 보인다 ── */
  {
    const h = harness();
    await h.connect();
    const scope = {
      document: h.doc,
      B66QuoteAppBridge: h.bridge,
      B66QuoteDriveClient: Client,
      B66QuoteDriveContract: Contract,
      B66_DRIVE_CLIENT_ID: CLIENT_ID
    };
    scope.document.readyState = "complete";
    Ui.resetBootstrapForTest();
    const originalWindow = globalThis.window;
    const originalDocument = globalThis.document;
    globalThis.window = scope;
    globalThis.document = h.doc;
    let handle = null;
    let installed = false;
    try {
      installed = Ui.installStartHook(scope, Ui);
      assert.equal(installed, true, "START_HOOK_INSTALLED");
      assert.equal(Ui.installStartHook(scope, Ui), false, "START_HOOK_ONCE_ONLY");
      await settle();
      handle = scope.B66QuoteDriveUiInstance;
    } finally {
      if (originalWindow === undefined) delete globalThis.window; else globalThis.window = originalWindow;
      if (originalDocument === undefined) delete globalThis.document; else globalThis.document = originalDocument;
    }
    assert.ok(handle && handle.ok === true, "BOOTSTRAP_MOUNTED");
    assert.equal(h.doc.container.children.length, 2, "MOUNTED_INTO_REAL_CONTAINER");
    assert.equal(handle.connectVisible(), true, "CONNECT_CONTROL_VISIBLE");
    assert.equal(handle.saveVisible(), true, "SAVE_CONTROL_VISIBLE");
    assert.equal(handle.openVisible(), true, "OPEN_CONTROL_VISIBLE");
    const actions = h.doc.container.children[1];
    const labels = actions.children.map((node) => node.textContent);
    assert.ok(labels.indexOf("내 Google Drive에 저장") !== -1, "SAVE_LABEL_PRESENT");
    assert.ok(labels.indexOf("Google Drive에서 열기") !== -1, "OPEN_LABEL_PRESENT");
    assert.ok(labels.some((label) => label.indexOf("Google Drive 연결") !== -1), "CONNECT_LABEL_PRESENT");
    const instanceAfter = scope.B66QuoteDriveUiInstance;
    Ui.bootstrap({ document: h.doc, client: h.client, bridge: h.bridge, contract: Contract });
    assert.equal(scope.B66QuoteDriveUiInstance, instanceAfter, "BOOTSTRAP_IDEMPOTENT");
    assert.equal(Ui.bootstrap({ document: h.doc, client: h.client, bridge: h.bridge, contract: Contract }),
      instanceAfter, "BOOTSTRAP_RETURNS_SAME_HANDLE");
    Ui.resetBootstrapForTest();
  }

  /* ── 4. 브리지가 없으면 제한된 횟수만 재시도하고 포기한다 ── */
  {
    Ui.resetBootstrapForTest();
    const scheduled = [];
    const fakeScope = { document: stubDocument() };
    const originalWindow = globalThis.window;
    globalThis.window = fakeScope;
    try {
      let result = null;
      for (let attempt = 0; attempt < 80; attempt += 1) {
        result = Ui.bootstrap({ document: fakeScope.document, client: null, setTimeout: (fn) => scheduled.push(fn) });
        if (result.code === "bridge_unavailable") break;
        /* 예약된 재시도 타이머가 실제로 발화한 것처럼 진행시킨다. */
        const fire = scheduled.shift();
        if (fire) fire();
      }
      assert.equal(result.code, "bridge_unavailable", "BOOTSTRAP_GIVES_UP_WITHOUT_BRIDGE");
      assert.ok(scheduled.length <= 41, "BOOTSTRAP_RETRIES_BOUNDED: " + scheduled.length);
    } finally {
      if (originalWindow === undefined) delete globalThis.window;
      else globalThis.window = originalWindow;
      Ui.resetBootstrapForTest();
    }
  }

  /* ── 5. 연결 후 정상 저장 → 성공 메시지 ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    await h.connect();
    const ui = h.mount();
    assert.equal(ui.session().connected, true, "connected");
    ui.click("save");
    await settle();
    assert.equal(ui.lastOutcome(), null, "완료 시 보류 쌍 없음");
    assert.ok(ui.statusText().indexOf("저장했습니다") !== -1, "SUCCESS_STATUS");
    assert.equal(ui.retryVisible(), false, "완료 시 재시도 버튼 숨김");
    assert.equal(h.state.created.length, 2, "UI_SAVED_TWO_FILES");
  }

  /* ── 6. 부분 성공은 성공으로 표시되지 않고 재시도 버튼이 나타난다 ── */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } },
        { mimeType: PDF_MIME }
      ]
    });
    await h.connect();
    const ui = h.mount();
    ui.click("save");
    await settle();
    assert.equal(ui.lastOutcome().status, "partial_json", "UI_PARTIAL_STATUS");
    assert.equal(ui.retryVisible(), true, "PARTIAL_RETRY_BUTTON_VISIBLE");
    assert.ok(ui.statusText().indexOf("실패") !== -1, "PARTIAL_MESSAGE_NOT_SILENT");

    const savedJsonId = ui.lastOutcome().json.id;
    h.state.metadataById[savedJsonId] = {
      id: savedJsonId, name: ui.lastOutcome().pair.jsonName, mimeType: JSON_MIME, size: 4000,
      trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
    };
    ui.click("retry");
    await settle();
    assert.ok(ui.statusText().indexOf("완료") !== -1, "UI_RETRY_COMPLETES");
    assert.equal(ui.retryVisible(), false, "RETRY_HIDDEN_AFTER_COMPLETE");
  }

  /* ── 7. 재시도 전 견적이 바뀌면 이어서 저장하지 않고 새 저장을 요구한다 ── */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    await h.connect();
    const ui = h.mount();
    ui.click("save");
    await settle();
    assert.equal(ui.retryVisible(), true, "partial before edit");
    const savedJsonId = ui.lastOutcome().json.id;
    h.state.metadataById[savedJsonId] = {
      id: savedJsonId, name: ui.lastOutcome().pair.jsonName, mimeType: JSON_MIME, size: 4000,
      trashed: false, owners: [{ me: true }]
    };
    h.current.draft = Core.normalizeDraft(Object.assign({}, h.current.draft, {
      items: [{ id: "item-1", name: "서비스 구축", qty: 42, unitPrice: 1000000 }]
    }));
    const uploadsBefore = h.state.created.length;
    ui.click("retry");
    await settle();
    assert.equal(h.state.created.length, uploadsBefore, "NO_UPLOAD_AFTER_EDIT");
    assert.equal(ui.retryVisible(), false, "STALE_RETRY_BUTTON_HIDDEN");
    assert.ok(ui.statusText().indexOf("바뀌었습니다") !== -1, "STALE_MESSAGE_SHOWN");
  }

  /* ── 8. PDF 를 만들지 못하면 업로드를 시작하지 않는다 ── */
  {
    const h = harness({ pdfOk: false, uploads: [{ mimeType: JSON_MIME }] });
    await h.connect();
    const ui = h.mount();
    ui.click("save");
    await settle();
    assert.equal(h.state.created.length, 0, "NO_UPLOAD_WITHOUT_PDF");
    assert.ok(ui.statusText().indexOf("pdf_source_unavailable") !== -1, "PDF 실패 코드 표면화");
  }

  /* ── 9. 불러오기: 승인 템플릿 확인 후 편집기 반영 ── */
  {
    const loaded = draftFixture();
    const media = packageTextFor(loaded, "pkg-ui-1");
    const h = harness({
      files: [{ id: "json-1", name: "견적서_PQ-20261009-011_가나상사.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-1": {
          id: "json-1", name: "a.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    await h.connect();
    const ui = h.mount();
    ui.click("open");
    await settle();
    assert.ok(ui.statusText().indexOf("선택해 주세요") !== -1, "FILE_LIST_PRESENTED");
    ui.click("confirmOpen");
    await settle();
    assert.equal(h.writes().length, 1, "DRAFT_APPLIED_TO_EDITOR");
    assert.deepEqual(h.current.draft, loaded, "LOADED_DRAFT_IDENTICAL");
    assert.ok(ui.statusText().indexOf("다시 계산") !== -1, "RECALCULATION_EXPLAINED");
  }

  /* ── 10. 승인 템플릿을 확인할 수 없으면 편집기에 적용하지 않는다 ── */
  {
    const loaded = draftFixture();
    const media = packageTextFor(loaded, "pkg-ui-2");
    const h = harness({
      approvedSkills: [],
      files: [{ id: "json-2", name: "b.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-2": {
          id: "json-2", name: "b.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    await h.connect();
    const ui = h.mount();
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.equal(h.writes().length, 0, "UNRESOLVED_TEMPLATE_NOT_APPLIED");
    assert.ok(ui.statusText().indexOf("자동 대체하지 않았습니다") !== -1, "TEMPLATE_BLOCK_EXPLAINED");
  }

  /* ── 11. 편집기 적용 실패를 성공으로 표시하지 않는다 ── */
  {
    const loaded = draftFixture();
    const media = packageTextFor(loaded, "pkg-ui-3");
    const base = {
      files: [{ id: "json-3", name: "c.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-3": {
          id: "json-3", name: "c.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    };
    for (const mode of ["fail", "throw"]) {
      const h = harness(Object.assign({}, base, { writeBehavior: { mode: mode } }));
      await h.connect();
      const before = JSON.parse(JSON.stringify(h.current.draft));
      const beforeTemplate = JSON.parse(JSON.stringify(h.current.template));
      const ui = h.mount();
      ui.click("open");
      await settle();
      ui.click("confirmOpen");
      await settle();
      assert.equal(ui.statusTone(), "error", "APPLY_FAILURE_IS_ERROR: " + mode);
      assert.ok(ui.statusText().indexOf("그대로 유지됩니다") !== -1, "APPLY_FAILURE_MESSAGE: " + mode);
      assert.deepEqual(h.current.draft, before, "APPLY_FAILURE_KEEPS_OLD_DRAFT: " + mode);
      assert.deepEqual(h.current.template, beforeTemplate, "APPLY_FAILURE_KEEPS_TEMPLATE: " + mode);
    }
  }

  /* ── 12. 편집기 반영 내용이 다르면 오류 표시 + 기존 내용·템플릿 보존(강화) ── */
  {
    const loaded = draftFixture();
    const media = packageTextFor(loaded, "pkg-ui-4");
    const h = harness({
      writeBehavior: { mode: "mismatch" },
      files: [{ id: "json-4", name: "d.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-4": {
          id: "json-4", name: "d.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    await h.connect();
    const before = JSON.parse(JSON.stringify(h.current.draft));
    const beforeTemplate = JSON.parse(JSON.stringify(h.current.template));
    const ui = h.mount();
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.equal(ui.statusTone(), "error", "READBACK_MISMATCH_IS_ERROR");
    assert.ok(ui.statusText().indexOf("그대로 유지됩니다") !== -1, "READBACK_MISMATCH_MESSAGE");
    assert.deepEqual(h.current.draft, before, "READBACK_MISMATCH_KEEPS_OLD_DRAFT");
    assert.deepEqual(h.current.template, beforeTemplate, "READBACK_MISMATCH_KEEPS_TEMPLATE");
    assert.ok(h.bridgeCalls.indexOf("restore:ok") !== -1, "ROLLBACK_WAS_PERFORMED");
  }

  /* ── 13. 사용자가 취소하면 편집 중 견적을 바꾸지 않는다 ── */
  {
    const loaded = draftFixture();
    const media = packageTextFor(loaded, "pkg-ui-5");
    const h = harness({
      files: [{ id: "json-5", name: "e.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-5": {
          id: "json-5", name: "e.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    await h.connect();
    const ui = h.mount({ confirm: () => false });
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.equal(h.writes().length, 0, "CANCEL_DOES_NOT_REPLACE_DRAFT");
    assert.ok(ui.statusText().indexOf("취소") !== -1, "CANCEL_EXPLAINED");
  }

  /* ── 14. B66 로그아웃은 Drive 토큰을 즉시 폐기한다 ── */
  {
    const h = harness({
      uploads: [
        { mimeType: JSON_MIME },
        { mimeType: PDF_MIME, status: 403, data: { error: { message: "quota" } } }
      ]
    });
    await h.connect();
    const ui = h.mount();
    ui.click("save");
    await settle();
    assert.equal(ui.retryVisible(), true, "partial pending before logout");
    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    assert.equal(ui.session().connected, false, "B66_LOGOUT_CLEARS_DRIVE_SESSION");
    assert.equal(ui.retryVisible(), false, "B66_LOGOUT_CLEARS_PENDING_PAIR");
    assert.equal(ui.saveDisabled(), true, "B66_LOGOUT_DISABLES_SAVE");
    assert.equal(ui.openDisabled(), true, "B66_LOGOUT_DISABLES_OPEN");
    assert.equal(ui.session().lastErrorCode, "b66_signed_out", "B66_LOGOUT_REASON_RECORDED");
    assert.ok(ui.statusText().indexOf("해제") !== -1, "B66_LOGOUT_STATUS");
  }

  /* ── 15. A→B 계정 전환도 Drive 세션을 폐기한다 ── */
  {
    const h = harness({ uploads: [] });
    await h.connect();
    const ui = h.mount();
    assert.equal(ui.session().connected, true, "connected before switch");
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true,
      privateStateReadable: false,
      action: "quarantined_foreign_owner"
    });
    await settle();
    assert.equal(ui.session().connected, false, "ACCOUNT_SWITCH_CLEARS_DRIVE_SESSION");

    await h.connect();
    const ui2 = h.mount();
    assert.equal(ui2.session().connected, true, "reconnected");
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true,
      privateStateReadable: true,
      action: "same_account_resume"
    });
    await settle();
    assert.equal(ui2.session().connected, true, "SAME_ACCOUNT_RESUME_KEEPS_SESSION");
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true,
      privateStateReadable: true,
      action: "owner_bound"
    });
    await settle();
    assert.equal(ui2.session().connected, true, "OWNER_BOUND_KEEPS_SESSION");
  }

  /* ── 16. 계정 전환 뒤 도착한 in-flight 저장 결과는 반영되지 않는다 ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    await h.connect();
    const ui = h.mount();
    let release = null;
    h.state.beforeResponse = (target) => {
      if (target.indexOf("/upload/drive") === -1) return undefined;
      return new Promise((resolve) => { release = resolve; });
    };
    ui.click("save");
    await settle();
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true,
      privateStateReadable: false,
      action: "quarantined_foreign_owner"
    });
    release();
    await settle();
    assert.equal(ui.lastOutcome(), null, "SUPERSEDED_SAVE_NOT_RECORDED");
    assert.ok(ui.statusText().indexOf("계정") !== -1, "SUPERSEDED_EXPLAINED");
    assert.ok(ui.statusText().indexOf("저장했습니다") === -1, "SUPERSEDED_NOT_REPORTED_AS_SUCCESS");
  }

  /* ── 17. 연결 해제 버튼 동작 ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    await h.connect();
    const ui = h.mount();
    ui.click("connect");
    await settle();
    assert.equal(ui.session().connected, false, "LOGOUT_APPLIED");
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_AFTER_LOGOUT");
    assert.ok(ui.statusText().indexOf("해제") !== -1, "LOGOUT_STATUS");
  }

  /* ── 18. Picker 설정이 있으면 선택기 경로가 열린다 ── */
  {
    const loaded = draftFixture();
    const media = packageTextFor(loaded, "pkg-ui-6");
    const h = harness({
      appId: "1234567890",
      developerKey: "dev-key",
      metadataById: {
        "picked-1": {
          id: "picked-1", name: "picked.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    await h.connect();
    const ui = h.mount();
    assert.equal(ui.pickerVisible(), true, "PICKER_BUTTON_VISIBLE_WHEN_CONFIGURED");
    h.client.openPicker = async () => ({ ok: true, code: "picked", picked: [{ id: "picked-1", name: "picked.json" }] });
    ui.click("picker");
    await settle();
    assert.equal(h.writes().length, 1, "PICKER_PATH_OPENS_FILE");
    assert.deepEqual(h.current.draft, loaded, "PICKER_LOADED_DRAFT_IDENTICAL");
  }

  /* ── 19. Picker 미지원이면 목록 경로로 대체한다 ── */
  {
    const loaded = draftFixture();
    const media = packageTextFor(loaded, "pkg-ui-7");
    const h = harness({
      appId: "1234567890",
      developerKey: "dev-key",
      files: [{ id: "json-7", name: "g.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-7": {
          id: "json-7", name: "g.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    await h.connect();
    const ui = h.mount();
    h.client.openPicker = async () => ({ ok: false, code: "picker_unavailable", picked: [] });
    ui.click("picker");
    await settle();
    assert.ok(ui.statusText().indexOf("목록에서 선택") !== -1, "PICKER_FALLBACK_EXPLAINED");
    ui.click("confirmOpen");
    await settle();
    assert.equal(h.writes().length, 1, "FALLBACK_LIST_PATH_WORKS");
  }

  /* ── 20. 런타임 설정 준비 상태 보고 (실제 연결 검증의 선행 조건) ── */
  {
    const none = Ui.describeConfiguration({ clientId: "", appId: "", developerKey: "" });
    assert.equal(none.configured, false, "READINESS_NOT_CONFIGURED");
    assert.equal(none.clientIdPresent, false, "READINESS_CLIENT_ID_ABSENT");
    assert.ok(none.missing.indexOf("B66_DRIVE_CLIENT_ID") !== -1, "READINESS_NAMES_CLIENT_ID");
    assert.ok(none.blocking.indexOf("B66_DRIVE_CLIENT_ID") !== -1, "READINESS_BLOCKING_CLIENT_ID");

    const malformed = Ui.describeConfiguration({ clientId: "not-a-client-id", appId: "", developerKey: "" });
    assert.equal(malformed.configured, false, "READINESS_MALFORMED_REJECTED");
    assert.ok(malformed.invalid.indexOf("B66_DRIVE_CLIENT_ID") !== -1, "READINESS_MALFORMED_NAMED");
    assert.ok(malformed.blocking.indexOf("B66_DRIVE_CLIENT_ID") !== -1, "READINESS_MALFORMED_BLOCKING");

    const ready = Ui.describeConfiguration({
      clientId: "1234567890-abcdef.apps.googleusercontent.com", appId: "", developerKey: ""
    });
    assert.equal(ready.configured, true, "READINESS_CONFIGURED");
    assert.equal(ready.clientIdShapeValid, true, "READINESS_CLIENT_ID_SHAPE_VALID");
    assert.equal(ready.pickerReady, false, "READINESS_PICKER_OPTIONAL_ABSENT");
    assert.deepEqual(ready.blocking, [], "READINESS_NO_BLOCKERS");

    const withPicker = Ui.describeConfiguration({
      clientId: "1234567890-abcdef.apps.googleusercontent.com", appId: "1234567890", developerKey: "browser-key"
    });
    assert.equal(withPicker.pickerReady, true, "READINESS_PICKER_READY");

    /* 값 자체는 어떤 형태로도 보고하지 않는다. */
    assert.equal(JSON.stringify(ready).indexOf("1234567890-abcdef"), -1, "READINESS_NEVER_ECHOES_VALUE");
    assert.equal(JSON.stringify(withPicker).indexOf("browser-key"), -1, "READINESS_NEVER_ECHOES_KEY");
  }

  /* ── 21. 설정 미준비 화면 안내가 누락 항목을 알려 주고 기존 기능을 유지한다 ── */
  {
    const h = harness({ clientId: "" });
    const ui = h.mount();
    assert.ok(ui.statusText().indexOf("B66_DRIVE_CLIENT_ID") !== -1, "STATUS_NAMES_MISSING_CONFIG");
    assert.ok(ui.statusText().indexOf("PDF 다운로드") !== -1, "STATUS_KEEPS_EXISTING_FEATURE_NOTE");
    assert.equal(ui.statusTone(), "info", "STATUS_TONE_INFO");
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_WHEN_NOT_CONFIGURED");
  }

  console.log("B66_DRIVE_UI=PASS");
  console.log("UI_CONTAINER_FAILS_CLOSED=PASS");
  console.log("UI_OPTIONAL_WITHOUT_CONFIG=PASS");
  console.log("UI_BOOTSTRAP_MOUNTS_ONCE=PASS");
  console.log("UI_CONTROLS_VISIBLE=PASS");
  console.log("UI_BOOTSTRAP_BOUNDED_WITHOUT_BRIDGE=PASS");
  console.log("UI_SAVE_SUCCESS_STATUS=PASS");
  console.log("UI_PARTIAL_NOT_SILENT=PASS");
  console.log("UI_STALE_RETRY_BLOCKED=PASS");
  console.log("UI_NO_UPLOAD_WITHOUT_PDF=PASS");
  console.log("UI_OPEN_REQUIRES_APPROVED_TEMPLATE=PASS");
  console.log("UI_APPLY_FAILURE_NOT_SUCCESS=PASS");
  console.log("UI_READBACK_VERIFIED=PASS");
  console.log("UI_CANCEL_PRESERVES_CURRENT_DRAFT=PASS");
  console.log("UI_B66_LOGOUT_REVOKES_DRIVE_TOKEN=PASS");
  console.log("UI_ACCOUNT_SWITCH_REVOKES_DRIVE_TOKEN=PASS");
  console.log("UI_IN_FLIGHT_DISCARDED_ON_ACCOUNT_CHANGE=PASS");
  console.log("UI_PICKER_PATH_WIRED=PASS");
  console.log("READINESS_REPORT_NAMES_MISSING_CONFIG=PASS");
  console.log("READINESS_NEVER_ECHOES_VALUES=PASS");
  console.log("SLICE_D_OFFLINE_TESTED=PASS");
})().catch((error) => {
  console.error("B66_DRIVE_UI=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
