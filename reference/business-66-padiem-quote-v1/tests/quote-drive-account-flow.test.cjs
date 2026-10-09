/* #3871 — 실제 로그인 버튼 → 로그아웃·계정 전환 흐름 테스트.
   이전 테스트는 Drive 가 이미 연결된 상태에서 시작해 다음을 놓쳤다.
     - OAuth 로그인 완료를 계정 전환으로 오인
     - OAuth 로그인 도중 B66 로그아웃 시 뒤늦은 토큰 연결
     - 정상적인 B66 로그인 상태 갱신에도 Drive 연결 해제
     - 다른 승인 템플릿 견적을 불러올 때 기존 편집 내용 보호
   여기서는 항상 **미연결 상태에서 시작**해 실제 버튼 흐름을 재현한다.
   네트워크·Google 계정·모델 호출은 사용하지 않는다(전부 주입 스텁). */
const assert = require("node:assert");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");
const Ui = require("../quote-drive-ui.js");

const CLIENT_ID = "test-client-id.apps.googleusercontent.com";
const JSON_MIME = Contract.JSON_MIME;
const SKILL_A = "b66skill_2eb55d822407f626b7a75c8c88d32c40";
const SKILL_B = "b66skill_11111111111111111111111111111111";
const TEMPLATE_A = { savedSkillId: SKILL_A, fingerprint: "fp-a", label: "A 양식" };
const TEMPLATE_B = { savedSkillId: SKILL_B, fingerprint: "fp-b", label: "B 양식" };
const APPROVED_BOTH = [
  { savedSkillId: SKILL_A, fingerprint: "fp-a", approved: true, active: true, label: "A 양식" },
  { savedSkillId: SKILL_B, fingerprint: "fp-b", approved: true, active: true, label: "B 양식" }
];

function stubDocument() {
  const registry = new Map();
  const docHandlers = {};
  function makeNode(tag) {
    return {
      tagName: tag, id: "", children: [], listeners: {}, className: "", type: "",
      hidden: false, disabled: false, textContent: "", value: "", dataset: {},
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
    dispatch(type, detail) { (docHandlers[type] || []).slice().forEach((handler) => handler({ detail: detail })); }
  };
}

function draftFixture() {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: "PQ-20261009-021", issueDate: "2026-10-09", validDays: 30, source: "manual" },
    sender: { company: "공급상사", rep: "김대표", bizNo: "123-45-67890", address: "서울", phone: "02-000-0000", email: "s@example.com", presetId: "custom" },
    recipient: { company: "가나상사", person: "박담당", address: "부산", email: "b@example.com" },
    items: [{ id: "item-1", name: "서비스 구축", qty: 1, unitPrice: 1000000 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: ""
  });
}

function packageText(draft, template, packageId) {
  const built = Contract.buildPackage({ draft, template, savedAt: "2026-10-09T09:00:00.000Z", packageId });
  assert.equal(built.ok, true, "fixture package builds");
  return Contract.serializePackage(built.package);
}

const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let index = 0; index < 30; index += 1) await flush(); };

function harness(options) {
  const opts = options || {};
  const doc = stubDocument();
  const state = {
    files: (opts.files || []).slice(),
    metadataById: opts.metadataById || {},
    media: opts.media === undefined ? null : opts.media,
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
  const fetchImpl = async (url) => {
    const target = String(url);
    if (target.indexOf("oauth2.googleapis.com/revoke") !== -1) return jsonResponse({}, 200);
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

  /* GIS 스텁: 팝업은 실제로 열리지 않고, 테스트가 승인/거부 시점을 직접 정한다. */
  const gis = { pending: null, opened: 0, scope: null };
  const google = {
    accounts: {
      oauth2: {
        initTokenClient(config) {
          gis.scope = config.scope;
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

  const calls = [];
  const frozen = Client.create({
    clientId: opts.clientId === undefined ? CLIENT_ID : opts.clientId,
    fetch: async (url, init) => { calls.push(String(url)); return fetchImpl(url, init); },
    google: google,
    gapi: null,
    loadScript: async () => { throw new Error("no network in test"); }
  });
  const client = Object.assign({}, frozen);

  const bridgeCalls = [];
  const current = { draft: opts.draft || draftFixture() };
  const bridge = {
    getDraft: () => { bridgeCalls.push("getDraft"); return current.draft; },
    replaceDraft: (draft) => {
      bridgeCalls.push("replaceDraft");
      current.draft = Core.normalizeDraft(draft);
      return { ok: true, draft: current.draft };
    },
    certifiedPdfBytes: async () => ({ ok: true, bytes: new Uint8Array(512).fill(0), fileName: "a.pdf" }),
    activeTemplateReference: () => (opts.activeTemplate === undefined ? TEMPLATE_A : opts.activeTemplate),
    listApprovedSkills: () => (opts.approvedSkills === undefined ? APPROVED_BOTH : opts.approvedSkills),
    hasMeaningfulDraft: () => opts.hasMeaningfulDraft === true,
    toast: () => {}
  };

  return {
    doc, client, state, calls, gis, bridgeCalls, current, bridge,
    mount(extra) {
      const base = { document: doc, client: client, bridge: bridge, contract: Contract };
      if (opts.confirm !== undefined) base.confirm = opts.confirm;
      return Ui.mount(Object.assign(base, extra || {}));
    },
    async approve(params) {
      await settle();
      assert.ok(typeof gis.pending === "function", "GIS callback registered");
      gis.pending(Object.assign({
        access_token: "late-token", expires_in: 3600, scope: Client.SCOPE_DRIVE_FILE
      }, params || {}));
    },
    async deny(errorName) {
      await settle();
      assert.ok(typeof gis.pending === "function", "GIS callback registered");
      gis.pending({ error: errorName || "access_denied" });
    },
    revokeCalls: () => calls.filter((url) => url.indexOf("oauth2.googleapis.com/revoke") !== -1)
  };
}

(async () => {
  /* ── 1. 미연결 상태에서 로그인 버튼 → 팝업 승인 → 연결 ── */
  {
    const h = harness();
    const ui = h.mount();
    assert.equal(ui.session().connected, false, "STARTS_DISCONNECTED");
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_BEFORE_CONNECT");
    ui.click("connect");
    await settle();
    assert.equal(h.gis.opened, 1, "OAUTH_POPUP_OPENED_FROM_BUTTON");
    assert.equal(h.gis.scope, Client.SCOPE_DRIVE_FILE, "LEAST_SCOPE_FROM_UI");
    assert.equal(ui.session().connectPending, true, "POPUP_PENDING");
    await h.approve();
    await settle();
    assert.equal(ui.session().connected, true, "CONNECTED_AFTER_APPROVAL");
    assert.equal(ui.saveDisabled(), false, "SAVE_ENABLED_AFTER_CONNECT");
    assert.ok(ui.statusText().indexOf("연결되었습니다") !== -1, "CONNECTED_STATUS");
  }

  /* ── 2. 팝업 거부 → 연결되지 않음 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.deny("access_denied");
    await settle();
    assert.equal(ui.session().connected, false, "DENIED_NOT_CONNECTED");
    assert.equal(ui.saveDisabled(), true, "SAVE_STILL_DISABLED");
    assert.equal(ui.statusTone(), "error", "DENIED_STATUS_TONE");
  }

  /* ── 3. 팝업 도중 B66 로그아웃 → 뒤늦은 토큰을 받지 않는다(보안) ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await settle();
    assert.equal(h.gis.opened, 1, "POPUP_OPEN");
    /* 팝업이 떠 있는 동안 B66 로그아웃 */
    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    await h.approve({ access_token: "late-token" });
    await settle();
    assert.equal(ui.session().connected, false, "LATE_TOKEN_NOT_CONNECTED");
    assert.equal(ui.saveDisabled(), true, "SAVE_STILL_DISABLED_AFTER_LATE_TOKEN");
    assert.equal(ui.statusTone(), "warn", "SUPERSEDED_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("취소") !== -1, "SUPERSEDED_STATUS_TEXT");
    const revokes = h.revokeCalls();
    assert.equal(revokes.length, 1, "LATE_TOKEN_REVOKED_ONCE");
    assert.ok(revokes[0].indexOf("late-token") !== -1, "REVOKE_TARGETS_LATE_TOKEN");
  }

  /* ── 4. 정상 B66 로그인/상태 갱신은 Drive 연결을 유지한다 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    assert.equal(ui.session().connected, true, "CONNECTED");

    h.doc.dispatch("b66:auth-changed", { authenticated: true });
    await settle();
    assert.equal(ui.session().connected, true, "AUTH_REFRESH_KEEPS_DRIVE_SESSION");
    assert.equal(ui.saveDisabled(), false, "SAVE_STILL_ENABLED");

    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: true, action: "same_account_resume"
    });
    await settle();
    assert.equal(ui.session().connected, true, "SAME_ACCOUNT_RESUME_KEEPS_SESSION");

    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: true, action: "owner_bound"
    });
    await settle();
    assert.equal(ui.session().connected, true, "OWNER_BOUND_KEEPS_SESSION");

    /* OAuth 완료 직후 오는 로그인 이벤트도 연결을 끊지 않는다 */
    h.doc.dispatch("b66:auth-changed", { authenticated: true });
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: true, action: "same_account_resume"
    });
    await settle();
    assert.equal(ui.session().connected, true, "LOGIN_COMPLETION_NOT_MISTAKEN_FOR_SWITCH");
    assert.equal(h.revokeCalls().length, 0, "NO_REVOKE_ON_NORMAL_REFRESH");
  }

  /* ── 5. B66 로그아웃은 연결 해제 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    assert.equal(ui.session().connected, false, "SIGN_OUT_DISCONNECTS");
    assert.equal(h.revokeCalls().length, 1, "TOKEN_REVOKED_ON_SIGN_OUT");
    assert.equal(ui.session().lastErrorCode, "b66_signed_out", "SIGN_OUT_REASON");
    assert.ok(ui.statusText().indexOf("해제") !== -1, "SIGN_OUT_STATUS");
  }

  /* ── 6. 계정 전환(A→B)은 연결 해제 ── */
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
    assert.equal(ui.session().connected, false, "ACCOUNT_SWITCH_DISCONNECTS");
    assert.equal(ui.session().lastErrorCode, "b66_account_changed", "SWITCH_REASON");
    assert.equal(ui.saveDisabled(), true, "SAVE_DISABLED_AFTER_SWITCH");
    assert.equal(ui.openDisabled(), true, "OPEN_DISABLED_AFTER_SWITCH");
  }

  /* ── 7. owner 확인 불가/미인증도 연결 해제 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: false, action: "authenticated_owner_unusable"
    });
    await settle();
    assert.equal(ui.session().connected, false, "OWNER_UNUSABLE_DISCONNECTS");

    await h.mount().click("connect");
    await h.approve();
    await settle();
    assert.equal(ui.session().connected, true, "RECONNECTED");
    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: false, privateStateReadable: false, action: null
    });
    await settle();
    assert.equal(ui.session().connected, false, "SCOPE_WITHOUT_ACTION_DISCONNECTS");
  }

  /* ── 8. 미연결 상태의 로그아웃 알림은 조용히 처리한다(오류 표시 없음) ── */
  {
    const h = harness();
    const ui = h.mount();
    const before = ui.statusText();
    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    assert.equal(ui.statusText(), before, "NO_NOISY_STATUS_WHEN_NOT_CONNECTED");
    assert.equal(ui.statusTone(), "info", "NO_ERROR_TONE_WHEN_NOT_CONNECTED");
    assert.equal(h.revokeCalls().length, 0, "NO_REVOKE_WITHOUT_TOKEN");
  }

  /* ── 9. 다른 승인 템플릿 견적 불러오기 → 편집 내용 보호 ── */
  {
    const loaded = draftFixture();
    const media = packageText(loaded, TEMPLATE_A, "pkg-tpl-a");
    const h = harness({
      activeTemplate: TEMPLATE_B,
      hasMeaningfulDraft: true,
      confirm: () => true,
      files: [{ id: "json-a", name: "a.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-a": {
          id: "json-a", name: "a.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    const beforeDraft = JSON.parse(JSON.stringify(h.current.draft));
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.equal(h.bridgeCalls.indexOf("replaceDraft"), -1, "OTHER_TEMPLATE_NOT_APPLIED");
    assert.deepEqual(h.current.draft, beforeDraft, "EXISTING_EDITOR_CONTENT_PROTECTED");
    assert.equal(ui.statusTone(), "warn", "OTHER_TEMPLATE_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("다른 승인 양식") !== -1, "OTHER_TEMPLATE_EXPLAINED");
    assert.ok(ui.statusText().indexOf("바꾸지 않았습니다") !== -1, "NO_SILENT_TEMPLATE_SWITCH");
  }

  /* ── 10. 같은 템플릿 + 편집 중 내용 + 확인 수단 없음 → 적용하지 않는다 ── */
  {
    const loaded = draftFixture();
    const media = packageText(loaded, TEMPLATE_A, "pkg-same");
    const h = harness({
      activeTemplate: TEMPLATE_A,
      hasMeaningfulDraft: true,
      files: [{ id: "json-b", name: "b.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-b": {
          id: "json-b", name: "b.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    const beforeDraft = JSON.parse(JSON.stringify(h.current.draft));
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.equal(h.bridgeCalls.indexOf("replaceDraft"), -1, "NO_CONFIRM_MEANS_NO_REPLACE");
    assert.deepEqual(h.current.draft, beforeDraft, "CONTENT_KEPT_WITHOUT_CONFIRM");
    assert.ok(ui.statusText().indexOf("취소") !== -1, "PROTECTIVE_CANCEL_EXPLAINED");
  }

  /* ── 11. 같은 템플릿 + 빈 편집기 → 확인 없이 적용 ── */
  {
    const loaded = draftFixture();
    const media = packageText(loaded, TEMPLATE_A, "pkg-blank");
    const h = harness({
      activeTemplate: TEMPLATE_A,
      hasMeaningfulDraft: false,
      files: [{ id: "json-c", name: "c.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-c": {
          id: "json-c", name: "c.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.ok(h.bridgeCalls.indexOf("replaceDraft") !== -1, "BLANK_EDITOR_APPLIES_WITHOUT_PROMPT");
    assert.deepEqual(h.current.draft, loaded, "LOADED_DRAFT_IDENTICAL");
  }

  /* ── 12. 같은 템플릿 + 편집 중 내용 + 확인 승인 → 적용 ── */
  {
    const loaded = draftFixture();
    const media = packageText(loaded, TEMPLATE_A, "pkg-confirm");
    const h = harness({
      activeTemplate: TEMPLATE_A,
      hasMeaningfulDraft: true,
      confirm: () => true,
      files: [{ id: "json-d", name: "d.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
      metadataById: {
        "json-d": {
          id: "json-d", name: "d.json", mimeType: JSON_MIME, size: Buffer.byteLength(media, "utf8"),
          trashed: false, owners: [{ me: true }], capabilities: { canDownload: true }
        }
      },
      media: media
    });
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    ui.click("open");
    await settle();
    ui.click("confirmOpen");
    await settle();
    assert.ok(h.bridgeCalls.indexOf("replaceDraft") !== -1, "CONFIRMED_REPLACE_APPLIES");
    assert.deepEqual(h.current.draft, loaded, "CONFIRMED_DRAFT_IDENTICAL");
  }

  /* ── 13. 연결 → 로그아웃 → 재연결 → 계정 전환 전체 흐름 ── */
  {
    const h = harness();
    const ui = h.mount();
    ui.click("connect");
    await h.approve();
    await settle();
    assert.equal(ui.session().connected, true, "FLOW_1_CONNECTED");

    h.doc.dispatch("b66:auth-changed", { authenticated: false });
    await settle();
    assert.equal(ui.session().connected, false, "FLOW_2_SIGNED_OUT");
    assert.equal(ui.session().lastErrorCode, "b66_signed_out", "FLOW_2_REASON");

    ui.click("connect");
    await h.approve();
    await settle();
    assert.equal(ui.session().connected, true, "FLOW_3_RECONNECTED");

    h.doc.dispatch("b66:account-scope-changed", {
      authenticated: true, privateStateReadable: true, action: "quarantined_foreign_owner"
    });
    await settle();
    assert.equal(ui.session().connected, false, "FLOW_4_SWITCHED");
    assert.equal(ui.session().lastErrorCode, "b66_account_changed", "FLOW_4_REASON");
    assert.equal(h.revokeCalls().length, 2, "FLOW_REVOKED_ONCE_PER_LOSS");
  }

  console.log("B66_DRIVE_ACCOUNT_FLOW=PASS");
  console.log("LOGIN_BUTTON_OPENS_OAUTH=PASS");
  console.log("LEAST_SCOPE_FROM_UI=PASS");
  console.log("OAUTH_DENIED_NOT_CONNECTED=PASS");
  console.log("LATE_TOKEN_AFTER_LOGOUT_REJECTED=PASS");
  console.log("NORMAL_LOGIN_REFRESH_KEEPS_DRIVE=PASS");
  console.log("SIGN_OUT_DISCONNECTS=PASS");
  console.log("ACCOUNT_SWITCH_DISCONNECTS=PASS");
  console.log("OWNER_UNUSABLE_DISCONNECTS=PASS");
  console.log("NO_NOISE_WHEN_NOT_CONNECTED=PASS");
  console.log("OTHER_APPROVED_TEMPLATE_PROTECTS_EDITOR=PASS");
  console.log("NO_CONFIRM_MEANS_NO_REPLACE=PASS");
  console.log("BLANK_EDITOR_APPLIES_WITHOUT_PROMPT=PASS");
  console.log("CONFIRMED_REPLACE_APPLIES=PASS");
  console.log("FULL_LOGIN_TO_SWITCH_FLOW=PASS");
})().catch((error) => {
  console.error("B66_DRIVE_ACCOUNT_FLOW=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
