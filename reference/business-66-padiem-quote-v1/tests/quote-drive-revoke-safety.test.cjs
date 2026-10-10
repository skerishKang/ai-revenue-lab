/* #3871 — Google Drive 연결 해제 안전성 회귀 테스트 (LOCAL3 OAuth 재사용 슬라이스).
   목적: 일반 연결 해제 / B66 로그아웃 / 계정 전환 / 취소·지연 팝업 콜백이
   Google `/revoke` 를 **단 한 번도** 호출하지 않는다는 것을 실제 모듈 함수로 증명한다.

   배경(CENTRAL 2026-10-10): Google 토큰 철회는 OAuth 클라이언트가 아니라 프로젝트 단위로
   적용되어, 같은 프로젝트를 쓰는 다른 파디엠 Google 기능(로그인 등)의 부여까지 무효화한다.
   따라서 routine 흐름은 이 브라우저 메모리의 Drive 토큰·스코프만 지우고 세대(epoch)를 올린다.

   실제 Google 계정·네트워크·모델 호출은 사용하지 않는다. 모든 통신은 주입된 스텁이며,
   revoke 엔드포인트로 나가는 요청은 별도로 계수해 0 을 강제한다. */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");
const Ui = require("../quote-drive-ui.js");
const { createStubDocument } = require("./drive-dom-fixtures.cjs");
const { createEditorBridge } = require("./quote-editor-stub.cjs");

const Fixtures = require("./drive-fixtures.cjs");
const CLIENT_ID = Fixtures.CLIENT_ID;
const JSON_MIME = Contract.JSON_MIME;
const PDF_MIME = Contract.PDF_MIME;
const SKILL_ID = Fixtures.SKILL_ID;
const TEMPLATE = Fixtures.templateReference();
const APPROVED = Fixtures.approvedTemplates({ label: "CGI" });
const REVOKE_MARKER = "oauth2.googleapis.com/revoke";

function draftFixture() {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: "PQ-20261010-001", issueDate: "2026-10-10", validDays: 30, source: "manual" },
    sender: { company: "공급상사", rep: "김대표", bizNo: "123-45-67890", address: "서울", phone: "02-000-0000", email: "s@example.com", presetId: "custom" },
    recipient: { company: "가나상사", person: "박담당", address: "부산", email: "b@example.com" },
    items: [{ id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: ""
  });
}

const pdfBytes = Fixtures.pdfBytes;

function stubDocument() {
  return createStubDocument(Ui.DEFAULT_CONTAINER_ID);
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let index = 0; index < 30; index += 1) await flush(); };

/* ── 스텁 하네스: 모든 fetch 를 기록하고 revoke 로 나가는 요청을 따로 센다 ── */
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
  const calls = [];
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
    /* revoke 로 나가는 요청은 절대 없어야 한다. 도달하면 200 을 주되 카운터에 남는다. */
    if (target.indexOf(REVOKE_MARKER) !== -1) return jsonResponse({}, 200);
    if (target.indexOf("/upload/drive/v3/files") !== -1) {
      const next = state.uploadQueue.shift();
      if (!next) return jsonResponse({ error: { message: "no stub" } }, 500);
      const id = "id-" + (state.created.length + 1);
      state.created.push({ id, name: next.name || "uploaded", mimeType: next.mimeType || "" });
      return jsonResponse({ id, name: next.name || "uploaded" });
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

  /* GIS 스텁: 팝업을 실제로 열지 않고 테스트가 승인/거부 시점을 정한다. */
  const gis = { pending: null, opened: 0, scope: null, clientId: null };
  const google = {
    accounts: {
      oauth2: {
        initTokenClient(config) {
          gis.scope = config.scope;
          gis.clientId = config.client_id;
          return {
            requestAccessToken() {
              gis.opened += 1;
              gis.pending = config.callback;
            }
          };
        }
      }
    }
  };

  const client = Object.assign({}, Client.create({
    clientId: opts.clientId === undefined ? CLIENT_ID : opts.clientId,
    fetch: async (url, init) => { calls.push(String(url)); return fetchImpl(url, init); },
    google: google,
    gapi: null,
    loadScript: async () => { throw new Error("no network in test"); }
  }));

  const editorHarness = createEditorBridge({
    draft: opts.draft || draftFixture(),
    activeTemplate: TEMPLATE,
    approvedSkills: APPROVED,
    hasMeaningfulDraft: false
  });

  return {
    doc, client, state, calls, gis,
    editor: editorHarness.editor,
    bridge: editorHarness.bridge,
    writes: editorHarness.writes,
    revokeCalls: () => calls.filter((url) => url.indexOf(REVOKE_MARKER) !== -1),
    driveCalls: () => calls.filter((url) => url.indexOf("googleapis.com") !== -1 && url.indexOf(REVOKE_MARKER) === -1),
    mount(extra) {
      return Ui.mount(Object.assign({
        document: doc, client: client, bridge: editorHarness.bridge, contract: Contract, confirm: () => true
      }, extra || {}));
    },
    async approve(params) {
      await settle();
      assert.ok(typeof gis.pending === "function", "GIS callback registered");
      gis.pending(Object.assign({
        access_token: "stub-access-token", expires_in: 3600, scope: Client.SCOPE_DRIVE_FILE
      }, params || {}));
    },
    async deny(errorName) {
      await settle();
      assert.ok(typeof gis.pending === "function", "GIS callback registered");
      gis.pending({ error: errorName || "access_denied" });
    }
  };
}

(async () => {
  const moduleDir = path.resolve(__dirname, "..");

  /* ── 0. 소스에 revoke 엔드포인트 선언 자체가 없다(정책 고정) ── */
  {
    const clientSource = fs.readFileSync(path.join(moduleDir, "quote-drive-client.js"), "utf8");
    const uiSource = fs.readFileSync(path.join(moduleDir, "quote-drive-ui.js"), "utf8");
    assert.equal(clientSource.indexOf(REVOKE_MARKER), -1, "CLIENT_DECLARES_NO_REVOKE_ENDPOINT");
    assert.equal(uiSource.indexOf(REVOKE_MARKER), -1, "UI_DECLARES_NO_REVOKE_ENDPOINT");
    assert.equal(/oauth2\.googleapis\.com/.test(clientSource), false, "CLIENT_NO_OAUTH2_REVOKE_HOST");
  }

  /* ── 1. 일반 연결 해제: revoke 0 · 토큰/스코프 즉시 제거 ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    assert.equal(h.client.session().connected, true, "CONNECTED_BEFORE_DISCONNECT");
    assert.deepEqual(h.client.session().scopes, [Client.SCOPE_DRIVE_FILE], "SCOPE_BEFORE_DISCONNECT");

    const out = await h.client.disconnect();
    assert.equal(out.ok, true, "DISCONNECT_OK");
    assert.equal(out.revoked, false, "DISCONNECT_REVOKED_FLAG_FALSE");
    assert.equal(out.googleRevoke, false, "DISCONNECT_GOOGLE_REVOKE_FALSE");
    assert.equal(h.client.session().connected, false, "DISCONNECT_CLEARS_CONNECTED");
    assert.deepEqual(h.client.session().scopes, [], "DISCONNECT_CLEARS_SCOPES");
    assert.equal(h.client.session().expiresAt, 0, "DISCONNECT_CLEARS_EXPIRY");
    assert.equal(h.client.session().connectedAt, null, "DISCONNECT_CLEARS_CONNECTED_AT");
    assert.equal(h.revokeCalls().length, 0, "ROUTINE_DISCONNECT_ZERO_REVOKE");
  }

  /* ── 2. B66 로그아웃 이벤트: revoke 0 · 로컬 세션만 비운다 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    assert.equal(ui.session().connected, true, "UI_CONNECTED");
    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    assert.equal(ui.session().connected, false, "LOGOUT_CLEARS_SESSION");
    assert.equal(ui.session().lastErrorCode, "b66_signed_out", "LOGOUT_REASON");
    assert.equal(h.revokeCalls().length, 0, "LOGOUT_ZERO_GOOGLE_REVOKE");
    /* 안내 문구가 로컬 해제임을 구분해 알린다. */
    assert.ok(ui.statusText().indexOf("해제") !== -1, "LOGOUT_STATUS_EXPLAINS_DISCONNECT");
    assert.ok(ui.statusText().indexOf("철회되지 않습니다") !== -1, "LOGOUT_STATUS_DISTINGUISHES_GLOBAL_REVOKE");
  }

  /* ── 3. 계정 전환 이벤트: revoke 0 · 즉시 격리 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: true, action: "quarantined_foreign_owner"
    });
    await settle();
    assert.equal(ui.session().connected, false, "SWITCH_CLEARS_SESSION");
    assert.equal(ui.session().lastErrorCode, "b66_account_changed", "SWITCH_REASON");
    assert.equal(ui.saveDisabled(), true, "SWITCH_DISABLES_SAVE");
    assert.equal(ui.openDisabled(), true, "SWITCH_DISABLES_OPEN");
    assert.equal(h.revokeCalls().length, 0, "SWITCH_ZERO_GOOGLE_REVOKE");
  }

  /* ── 4. 정상 로그인/세션 갱신은 연결을 유지하고 revoke 0 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    h.doc.dispatch("b66:auth-changed", { authenticated: true });
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: true, action: "same_account_resume"
    });
    await settle();
    assert.equal(ui.session().connected, true, "REFRESH_KEEPS_SESSION");
    assert.equal(h.revokeCalls().length, 0, "REFRESH_ZERO_GOOGLE_REVOKE");
  }

  /* ── 5. 팝업 대기 중 로그아웃 → 늦은 토큰 폐기 · revoke 0 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await settle();
    assert.equal(h.gis.opened, 1, "POPUP_OPENED");
    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    await h.approve({ access_token: "late-token" });
    await settle();
    assert.equal(ui.session().connected, false, "LATE_TOKEN_NOT_CONNECTED");
    assert.equal(ui.statusTone(), "warn", "LATE_TOKEN_WARN_TONE");
    assert.equal(h.revokeCalls().length, 0, "LATE_TOKEN_ZERO_GOOGLE_REVOKE");
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_AFTER_LATE_TOKEN");
  }

  /* ── 6. 팝업 취소/거부: revoke 0 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.deny("popup_closed");
    await settle();
    assert.equal(ui.session().connected, false, "CANCELLED_NOT_CONNECTED");
    assert.equal(h.revokeCalls().length, 0, "CANCELLED_ZERO_GOOGLE_REVOKE");
  }

  /* ── 7. 이전 계정 토큰으로는 접근할 수 없다(로그아웃 후 네트워크 요청 0) ── */
  {
    const h = harness({ files: [{ id: "a", name: "mine.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    await h.client.disconnect({ reason: "b66_signed_out" });
    const driveBefore = h.driveCalls().length;
    assert.equal((await h.client.listQuoteFiles()).code, "drive_not_connected", "LOGOUT_BLOCKS_LIST");
    assert.equal((await h.client.savePair({ draft: draftFixture(), pdfBytes: pdfBytes() })).code,
      "drive_not_connected", "LOGOUT_BLOCKS_SAVE");
    assert.equal(h.driveCalls().length, driveBefore, "NO_DRIVE_TRAFFIC_AFTER_LOGOUT");
    assert.equal(h.revokeCalls().length, 0, "LOGOUT_NO_REVOKE_ON_BLOCKED_ACCESS");
  }

  /* ── 8. 계정 전환 뒤 도착한 in-flight 응답은 버려진다(epoch) ── */
  {
    const h = harness({ files: [{ id: "a", name: "mine.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }] });
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
    await h.client.disconnect({ reason: "b66_account_changed" });
    release();
    const result = await listing;
    assert.equal(result.ok, false, "IN_FLIGHT_DISCARDED");
    assert.equal(result.code, "drive_session_changed", "EPOCH_GUARD");
    assert.deepEqual(result.files, [], "NO_FILES_LEAKED");
    assert.equal(h.revokeCalls().length, 0, "EPOCH_DISCARD_ZERO_REVOKE");
  }

  /* ── 9. 같은 owner 로 정상 재연결 ── */
  {
    const h = harness({ uploads: [{ mimeType: JSON_MIME }, { mimeType: PDF_MIME }] });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    await h.client.disconnect();
    assert.equal(h.client.session().connected, false, "DISCONNECTED_BEFORE_RECONNECT");

    const again = h.client.connect({ prompt: "select_account" });
    await h.approve();
    const reconnected = await again;
    assert.equal(reconnected.ok, true, "RECONNECT_OK");
    assert.equal(h.client.session().connected, true, "RECONNECTED_CONNECTED");
    const saved = await h.client.savePair({ draft: draftFixture(), template: TEMPLATE, pdfBytes: pdfBytes() });
    assert.equal(saved.status, "complete", "RECONNECTED_SAVE_WORKS");
    assert.equal(h.revokeCalls().length, 0, "RECONNECT_ZERO_GOOGLE_REVOKE");
  }

  /* ── 10. 요청 스코프는 drive.file 하나뿐이다 ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await settle();
    assert.equal(h.gis.scope, Client.SCOPE_DRIVE_FILE, "SCOPE_IS_DRIVE_FILE_ONLY");
    assert.equal(h.gis.scope.indexOf("drive.readonly"), -1, "NO_BLANKET_READONLY_SCOPE");
    assert.equal(h.gis.scope.indexOf("drive "), -1, "NO_FULL_DRIVE_SCOPE");
    assert.equal(h.gis.scope.split(/\s+/).length, 1, "SINGLE_SCOPE_REQUESTED");
    await h.approve();
    await pending;
    assert.deepEqual(h.client.session().scopes, [Client.SCOPE_DRIVE_FILE], "GRANTED_SCOPE_DRIVE_FILE");
  }

  /* ── 11. 토큰은 어떤 브라우저 저장소에도 기록되지 않는다 ── */
  {
    const h = harness();
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const session = h.client.session();
    assert.equal(Object.prototype.hasOwnProperty.call(session, "accessToken"), false, "TOKEN_NOT_IN_PUBLIC_SESSION");
    assert.equal(JSON.stringify(session).indexOf("stub-access-token"), -1, "TOKEN_VALUE_NEVER_SURFACED");
    const clientSource = fs.readFileSync(path.join(moduleDir, "quote-drive-client.js"), "utf8");
    assert.equal(/localStorage|sessionStorage|indexedDB|document\.cookie/.test(clientSource), false,
      "NO_PERSISTENT_STORAGE_IN_CLIENT");
  }

  /* ── 12. 기존 기능 불변: QuoteCore 재계산 · 승인 템플릿 권위 ── */
  {
    const draft = draftFixture();
    const built = Contract.buildPackage({ draft, template: TEMPLATE, savedAt: "2026-10-10T09:00:00.000Z", packageId: "pkg-revoke-1" });
    const text = Contract.serializePackage(built.package);
    const h = harness({
      metadataById: {
        "file-1": {
          id: "file-1", name: "q.json", mimeType: JSON_MIME, size: Buffer.byteLength(text, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: text
    });
    const pending = h.client.connect();
    await h.approve();
    await pending;
    const opened = await h.client.openQuoteFile("file-1", { templates: APPROVED });
    assert.equal(opened.ok, true, "QUOTE_OPEN_STILL_WORKS");
    assert.equal(opened.totalsAuthority, "quote-core", "QUOTECORE_STILL_AUTHORITY");
    const expected = Core.computeDraftTotals(draft);
    assert.equal(opened.totals.grand, expected.grand, "QUOTECORE_RECALCULATES_ON_IMPORT");
    assert.equal(opened.template.status, "resolved", "APPROVED_TEMPLATE_STILL_RESOLVED");
    assert.equal(h.revokeCalls().length, 0, "IMPORT_ZERO_GOOGLE_REVOKE");
  }

  /* ── 13. 로그아웃이 D1/일반 PDF 경로에 개입하지 않는다(revoke 부재) ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    assert.equal(h.revokeCalls().length, 0, "LOGOUT_DOES_NOT_TOUCH_GOOGLE_PROJECT");
    /* 로그아웃은 Drive 세션만 비운다. 편집기 draft 는 건드리지 않는다. */
    assert.equal(h.writes().length, 0, "LOGOUT_DOES_NOT_WRITE_EDITOR");
  }

  console.log("B66_DRIVE_REVOKE_SAFETY=PASS");
  console.log("ROUTINE_GOOGLE_REVOKE_CALLS=0");
  console.log("DISCONNECT_LOCAL_TOKEN_CLEAR=PASS");
  console.log("LOGOUT_LOCAL_TOKEN_CLEAR=PASS");
  console.log("ACCOUNT_SWITCH_LOCAL_TOKEN_CLEAR=PASS");
  console.log("LATE_CALLBACK_REJECTED=PASS");
  console.log("LATE_CALLBACK_ZERO_REVOKE=PASS");
  console.log("IN_FLIGHT_ACCOUNT_EPOCH=PASS");
  console.log("PREVIOUS_ACCOUNT_ACCESS=DENIED");
  console.log("RECONNECT_UNDER_SAME_OWNER=PASS");
  console.log("DRIVE_FILE_SCOPE_ONLY=PASS");
  console.log("TOKEN_NOT_PERSISTED=PASS");
  console.log("QUOTECORE_AND_TEMPLATE_UNCHANGED=PASS");
  console.log("NO_SOURCE_REVOKE_ENDPOINT=PASS");
})().catch((error) => {
  console.error("B66_DRIVE_REVOKE_SAFETY=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
