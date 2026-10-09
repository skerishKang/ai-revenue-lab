/* #3871 — 견적 불러오기 실패 시 기존 편집 내용·템플릿 보존 회귀 테스트.
   CENTRAL revision-3 지적: 불러오기가 실패하면 사용자가 작성 중이던 내용과
   선택된 승인 템플릿이 그대로 유지되어야 한다.

   필수 시나리오
     1. 승인 템플릿 A로 작성 중인데 다른 승인 템플릿 B의 견적을 열려고 할 때
     2. replaceDraft() 가 실패를 반환할 때
     3. replaceDraft() 가 편집 내용을 일부 수정한 뒤 예외를 발생시킬 때
     4. 적용 결과의 content fingerprint 가 다를 때
     5. 적용 직전 계정이 로그아웃되거나 전환될 때
     6. 정상적인 견적 불러오기는 계속 성공하는지
   추가: 복구 자체가 실패하면 UI 가 보존을 주장하지 않는지. */
const assert = require("node:assert");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Client = require("../quote-drive-client.js");
const Ui = require("../quote-drive-ui.js");
const { createStubDocument } = require("./drive-dom-fixtures.cjs");
const { createEditorBridge, clone } = require("./quote-editor-stub.cjs");

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
  return createStubDocument(Ui.DEFAULT_CONTAINER_ID);
}

/* 작성 중이던 견적(사용자 내용) — 실패 시 이 값이 그대로여야 한다. */
function workingDraft() {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: "PQ-WORKING", issueDate: "2026-10-09", validDays: 30, source: "manual" },
    sender: { company: "작성중공급사", rep: "김대표", bizNo: "111-11-11111", address: "서울", phone: "02-111-1111", email: "w@example.com", presetId: "custom" },
    recipient: { company: "작성중고객사", person: "이담당", address: "서울", email: "c@example.com" },
    items: [{ id: "item-1", name: "작성 중 항목", qty: 7, unitPrice: 1234567 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: "작성 중 메모"
  });
}

/* Drive 에서 내려받을 견적. */
function remoteDraft(quoteNo) {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: quoteNo || "PQ-REMOTE", issueDate: "2026-10-01", validDays: 15, source: "manual" },
    sender: { company: "원격공급사", rep: "박대표", bizNo: "222-22-22222", address: "부산", phone: "051-222-2222", email: "r@example.com", presetId: "custom" },
    recipient: { company: "원격고객사", person: "최담당", address: "부산", email: "d@example.com" },
    items: [{ id: "item-1", name: "원격 항목", qty: 2, unitPrice: 500000 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: "원격 메모"
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
  const remote = opts.remote || remoteDraft();
  const remoteTemplate = opts.remoteTemplate || TEMPLATE_A;
  const media = packageText(remote, remoteTemplate, opts.packageId || "pkg-import");

  const state = {
    metadataById: {
      "json-1": {
        id: "json-1", name: "remote.json", mimeType: JSON_MIME,
        size: Buffer.byteLength(media, "utf8"), trashed: false,
        owners: [{ me: true }], capabilities: { canDownload: true }
      }
    },
    files: [{ id: "json-1", name: "remote.json", mimeType: JSON_MIME, trashed: false, owners: [{ me: true }] }],
    media: media,
    beforeResponse: null
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
    if (typeof state.beforeResponse === "function") await state.beforeResponse(target);
    if (target.indexOf("oauth2.googleapis.com/revoke") !== -1) return jsonResponse({}, 200);
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
    if (target.indexOf("/drive/v3/files?") !== -1) return jsonResponse({ files: state.files });
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
  const client = Object.assign({}, Client.create({
    clientId: CLIENT_ID,
    fetch: fetchImpl,
    google: google,
    gapi: null,
    loadScript: async () => { throw new Error("no network in test"); }
  }));

  const editorHarness = createEditorBridge({
    draft: opts.draft || workingDraft(),
    activeTemplate: opts.activeTemplate === undefined ? TEMPLATE_A : opts.activeTemplate,
    approvedSkills: opts.approvedSkills === undefined ? APPROVED_BOTH : opts.approvedSkills,
    hasMeaningfulDraft: opts.hasMeaningfulDraft === true,
    writeBehavior: opts.writeBehavior,
    restoreFails: opts.restoreFails === true
  });
  const bridge = editorHarness.bridge;
  const calls = editorHarness.calls;

  /* 커밋 지점(가드 직전)에 이벤트를 주입하기 위한 래퍼. */
  if (typeof opts.dispatchAtCommit === "function") {
    const inner = bridge.applyImportedDraft;
    bridge.applyImportedDraft = (nextDraft, applyOptions) => {
      const o = Object.assign({}, applyOptions || {});
      const innerGuard = o.beforeApply;
      o.beforeApply = () => {
        opts.dispatchAtCommit();
        return typeof innerGuard === "function" ? innerGuard() : { ok: true };
      };
      return inner(nextDraft, o);
    };
  }

  return {
    doc, client, state, bridge, calls,
    editor: editorHarness.editor,
    writes: editorHarness.writes,
    mount(extra) {
      const base = { document: doc, client: client, bridge: bridge, contract: Contract, confirm: () => true };
      return Ui.mount(Object.assign(base, extra || {}));
    },
    async connect() {
      const pending = client.connect();
      await flush();
      tokenCallback({ access_token: "stub-token", expires_in: 3600, scope: Client.SCOPE_DRIVE_FILE });
      await pending;
    }
  };
}

async function runImport(h, ui) {
  ui.click("open");
  await settle();
  ui.click("confirmOpen");
  await settle();
}

(async () => {
  /* ── 1. 템플릿 A 로 작성 중인데 템플릿 B 의 견적을 열려고 할 때 ── */
  {
    const h = harness({ remoteTemplate: TEMPLATE_B, activeTemplate: TEMPLATE_A, hasMeaningfulDraft: true });
    await h.connect();
    const before = clone(h.editor.draft);
    const beforeTemplate = clone(h.editor.template);
    const ui = h.mount();
    await runImport(h, ui);
    assert.equal(h.writes().length, 0, "S1_NO_WRITE");
    assert.deepEqual(h.editor.draft, before, "S1_OLD_DRAFT_PRESERVED");
    assert.deepEqual(h.editor.template, beforeTemplate, "S1_ACTIVE_TEMPLATE_PRESERVED");
    assert.equal(ui.statusTone(), "warn", "S1_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("다른 승인 양식") !== -1, "S1_STATUS_EXPLAINS_TEMPLATE");
  }

  /* ── 2. replaceDraft 가 실패를 반환할 때 ── */
  {
    const h = harness({ writeBehavior: { mode: "fail" }, hasMeaningfulDraft: true });
    await h.connect();
    const before = clone(h.editor.draft);
    const beforeTemplate = clone(h.editor.template);
    const ui = h.mount();
    await runImport(h, ui);
    assert.ok(h.writes().length > 0, "S2_WRITE_ATTEMPTED");
    assert.deepEqual(h.editor.draft, before, "S2_OLD_DRAFT_PRESERVED");
    assert.deepEqual(h.editor.template, beforeTemplate, "S2_ACTIVE_TEMPLATE_PRESERVED");
    assert.equal(ui.statusTone(), "error", "S2_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("그대로 유지됩니다") !== -1, "S2_PRESERVATION_REPORTED");
    assert.ok(h.calls.indexOf("restore:ok") !== -1, "S2_ROLLBACK_PERFORMED");
  }

  /* ── 3. 일부 수정 후 예외 ── */
  {
    const h = harness({ writeBehavior: { mode: "throwAfterPartial" }, hasMeaningfulDraft: true });
    await h.connect();
    const before = clone(h.editor.draft);
    const beforeTemplate = clone(h.editor.template);
    const ui = h.mount();
    await runImport(h, ui);
    assert.equal(h.calls.indexOf("write:throwAfterPartial") !== -1, true, "S3_PARTIAL_MUTATION_HAPPENED");
    assert.deepEqual(h.editor.draft, before, "S3_OLD_DRAFT_PRESERVED_AFTER_EXCEPTION");
    assert.deepEqual(h.editor.template, beforeTemplate, "S3_ACTIVE_TEMPLATE_PRESERVED_AFTER_EXCEPTION");
    assert.equal(h.editor.draft.memo, "작성 중 메모", "S3_PARTIAL_MUTATION_ROLLED_BACK");
    assert.ok(h.calls.indexOf("restore:ok") !== -1, "S3_ROLLBACK_PERFORMED");
    assert.ok(ui.statusText().indexOf("그대로 유지됩니다") !== -1, "S3_PRESERVATION_REPORTED");
  }

  /* ── 4. 적용 결과 content fingerprint 불일치 ── */
  {
    const h = harness({ writeBehavior: { mode: "mismatch" }, hasMeaningfulDraft: true });
    await h.connect();
    const before = clone(h.editor.draft);
    const beforeTemplate = clone(h.editor.template);
    const ui = h.mount();
    await runImport(h, ui);
    assert.equal(h.calls.indexOf("write:mismatch") !== -1, true, "S4_MISMATCHING_WRITE_HAPPENED");
    assert.deepEqual(h.editor.draft, before, "S4_OLD_DRAFT_PRESERVED");
    assert.deepEqual(h.editor.template, beforeTemplate, "S4_ACTIVE_TEMPLATE_PRESERVED");
    assert.ok(h.calls.indexOf("restore:ok") !== -1, "S4_ROLLBACK_PERFORMED");
    assert.equal(ui.statusTone(), "error", "S4_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("그대로 유지됩니다") !== -1, "S4_PRESERVATION_REPORTED");
  }

  /* ── 5a. 다운로드 중 로그아웃 → 적용 전 중단 ── */
  {
    const h = harness({ hasMeaningfulDraft: true });
    await h.connect();
    const before = clone(h.editor.draft);
    const beforeTemplate = clone(h.editor.template);
    const ui = h.mount();
    let dispatched = false;
    h.state.beforeResponse = async (target) => {
      if (dispatched) return;
      if (target.indexOf("alt=media") === -1) return;
      dispatched = true;
      h.doc.dispatch("b66:auth-changed", { authenticated: false });
    };
    await runImport(h, ui);
    assert.equal(dispatched, true, "S5A_LOGOUT_DURING_DOWNLOAD");
    assert.equal(h.writes().length, 0, "S5A_NO_WRITE");
    assert.deepEqual(h.editor.draft, before, "S5A_OLD_DRAFT_PRESERVED");
    assert.deepEqual(h.editor.template, beforeTemplate, "S5A_ACTIVE_TEMPLATE_PRESERVED");
    assert.ok(ui.statusText().indexOf("취소") !== -1, "S5A_CANCELLED_EXPLAINED");
  }

  /* ── 5b. 다운로드 중 계정 전환 → 적용 전 중단 ── */
  {
    const h = harness({ hasMeaningfulDraft: true });
    await h.connect();
    const before = clone(h.editor.draft);
    const ui = h.mount();
    let dispatched = false;
    h.state.beforeResponse = async (target) => {
      if (dispatched) return;
      if (target.indexOf("alt=media") === -1) return;
      dispatched = true;
      h.doc.dispatch("b66:account-scope-changed", {
        authenticated: true, privateStateReadable: true, action: "quarantined_foreign_owner"
      });
    };
    await runImport(h, ui);
    assert.equal(dispatched, true, "S5B_SWITCH_DURING_DOWNLOAD");
    assert.equal(h.writes().length, 0, "S5B_NO_WRITE");
    assert.deepEqual(h.editor.draft, before, "S5B_OLD_DRAFT_PRESERVED");
    assert.ok(ui.statusText().indexOf("취소") !== -1, "S5B_CANCELLED_EXPLAINED");
  }

  /* ── 5c. 커밋 지점에서 로그아웃 → 가드가 막는다 ── */
  {
    const h = harness({
      hasMeaningfulDraft: true,
      dispatchAtCommit: () => {
        h.doc.dispatch("b66:auth-changed", { authenticated: false });
      }
    });
    await h.connect();
    const before = clone(h.editor.draft);
    const beforeTemplate = clone(h.editor.template);
    const ui = h.mount();
    await runImport(h, ui);
    assert.equal(h.writes().length, 0, "S5C_COMMIT_GUARD_NO_WRITE");
    assert.deepEqual(h.editor.draft, before, "S5C_OLD_DRAFT_PRESERVED");
    assert.deepEqual(h.editor.template, beforeTemplate, "S5C_ACTIVE_TEMPLATE_PRESERVED");
    assert.equal(ui.statusTone(), "error", "S5C_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("그대로 유지됩니다") !== -1, "S5C_PRESERVATION_REPORTED");
  }

  /* ── 6. 정상 불러오기는 계속 성공한다 ── */
  {
    const h = harness({ hasMeaningfulDraft: false, activeTemplate: TEMPLATE_A, remoteTemplate: TEMPLATE_A });
    await h.connect();
    const ui = h.mount();
    await runImport(h, ui);
    assert.equal(h.writes().length, 1, "S6_WRITE_ONCE");
    assert.equal(h.editor.draft.meta.quoteNo, "PQ-REMOTE", "S6_REMOTE_DRAFT_APPLIED");
    assert.equal(ui.statusTone(), "ok", "S6_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("불러왔습니다") !== -1, "S6_SUCCESS_STATUS");
    assert.equal(h.calls.indexOf("restore:ok"), -1, "S6_NO_ROLLBACK_ON_SUCCESS");
  }

  /* ── 6b. 편집 중 내용이 있어도 확인하면 정상 적용된다 ── */
  {
    const h = harness({ hasMeaningfulDraft: true, activeTemplate: TEMPLATE_A, remoteTemplate: TEMPLATE_A });
    await h.connect();
    const ui = h.mount();
    await runImport(h, ui);
    assert.equal(h.writes().length, 1, "S6B_CONFIRMED_WRITE_ONCE");
    assert.equal(h.editor.draft.meta.quoteNo, "PQ-REMOTE", "S6B_REMOTE_DRAFT_APPLIED");
    assert.equal(ui.statusTone(), "ok", "S6B_STATUS_TONE");
  }

  /* ── 7. 복구 자체가 실패하면 보존을 주장하지 않는다 ── */
  {
    const h = harness({
      writeBehavior: { mode: "mismatch" },
      restoreFails: true,
      hasMeaningfulDraft: true
    });
    await h.connect();
    const ui = h.mount();
    await runImport(h, ui);
    assert.equal(h.calls.indexOf("restore:failed") !== -1, true, "S7_ROLLBACK_ATTEMPTED");
    assert.equal(ui.statusTone(), "error", "S7_STATUS_TONE");
    assert.ok(ui.statusText().indexOf("복구했다고 확인하지 못했습니다") !== -1,
      "S7_NO_FALSE_PRESERVATION_CLAIM");
    assert.equal(ui.statusText().indexOf("그대로 유지됩니다"), -1, "S7_DOES_NOT_CLAIM_PRESERVATION");
  }

  console.log("B66_DRIVE_IMPORT_SAFETY=PASS");
  console.log("S1_OTHER_TEMPLATE_PROTECTS_EDITOR=PASS");
  console.log("S2_REPLACE_FAILURE_PRESERVES_EDITOR=PASS");
  console.log("S3_PARTIAL_MUTATION_THEN_THROW_PRESERVES_EDITOR=PASS");
  console.log("S4_READBACK_MISMATCH_ROLLS_BACK=PASS");
  console.log("S5A_LOGOUT_DURING_DOWNLOAD_NO_MUTATION=PASS");
  console.log("S5B_SWITCH_DURING_DOWNLOAD_NO_MUTATION=PASS");
  console.log("S5C_COMMIT_POINT_GUARD=PASS");
  console.log("S6_NORMAL_IMPORT_STILL_SUCCEEDS=PASS");
  console.log("S6B_CONFIRMED_IMPORT_SUCCEEDS=PASS");
  console.log("S7_NO_FALSE_PRESERVATION_CLAIM=PASS");
})().catch((error) => {
  console.error("B66_DRIVE_IMPORT_SAFETY=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
