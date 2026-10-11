/* #3871 — 불러오기 적용 원자성 단위 테스트 (CENTRAL revision-3 지적).
   편집기를 직접 만지지 않는 순수 로직이므로 주입된 훅만으로 전 경로를 검증한다. */
const assert = require("node:assert");
const Core = require("../quote-core.js");
const Contract = require("../quote-drive-contract.js");
const Atomic = require("../quote-import-atomic.js");

const SKILL_A = "b66skill_2eb55d822407f626b7a75c8c88d32c40";
const SKILL_B = "b66skill_11111111111111111111111111111111";
const TEMPLATE_A = { savedSkillId: SKILL_A, fingerprint: "fp-a" };
const TEMPLATE_B = { savedSkillId: SKILL_B, fingerprint: "fp-b" };

const clone = (value) => JSON.parse(JSON.stringify(value));

function draftFixture(quoteNo, unitPrice) {
  return Core.normalizeDraft({
    schemaVersion: Core.SCHEMA_VERSION,
    meta: { quoteNo: quoteNo || "PQ-OLD", issueDate: "2026-10-09", validDays: 30, source: "manual" },
    sender: { company: "공급상사", rep: "김대표", bizNo: "123-45-67890", address: "서울", phone: "02-000-0000", email: "s@example.com", presetId: "custom" },
    recipient: { company: "가나상사", person: "박담당", address: "부산", email: "b@example.com" },
    items: [{ id: "item-1", name: "서비스 구축", qty: 1, unitPrice: unitPrice || 1000000 }],
    tax: { mode: "EXCLUSIVE", rate: 0.1 },
    memo: ""
  });
}

/* 편집기 대역: write 동작을 시나리오별로 바꾼다. */
function editor(options) {
  const opts = options || {};
  const state = {
    draft: clone(opts.draft || draftFixture("PQ-OLD", 1000000)),
    template: clone(opts.template || TEMPLATE_A),
    selectionRaw: "sel-initial"
  };
  const calls = [];
  return {
    state, calls,
    fingerprint: (value) => Contract.contentFingerprint(value, TEMPLATE_A),
    hooks(extra) {
      return Object.assign({
        fingerprint: (value) => Contract.contentFingerprint(value, TEMPLATE_A),
        normalize: (value) => Core.normalizeDraft(value),
        readDraft: () => { calls.push("read"); return clone(state.draft); },
        writeDraft: (value) => {
          const mode = opts.writeMode || "ok";
          if (mode === "throwAfterPartial") {
            state.draft = Core.normalizeDraft(Object.assign({}, value, { memo: "부분 변이" }));
            calls.push("write:throwAfterPartial");
            throw new Error("partial mutation then throw");
          }
          if (mode === "fail") { calls.push("write:fail"); return { ok: false, error: "invalid_draft" }; }
          if (mode === "throw") { calls.push("write:throw"); throw new Error("boom"); }
          if (mode === "mismatch") {
            state.draft = Core.normalizeDraft(Object.assign({}, value, { memo: "다른 내용" }));
            calls.push("write:mismatch");
            return { ok: true };
          }
          state.draft = Core.normalizeDraft(value);
          calls.push("write:ok");
          return { ok: true, draft: clone(state.draft) };
        },
        snapshot: () => {
          if (opts.snapshotFails === true) throw new Error("snapshot failed");
          calls.push("snapshot");
          return { draft: clone(state.draft), template: clone(state.template), selectionRaw: state.selectionRaw };
        },
        restore: (snap) => {
          if (opts.restoreFails === true) { calls.push("restore:failed"); return false; }
          if (opts.restoreThrows === true) { calls.push("restore:throw"); throw new Error("restore failed"); }
          state.draft = Core.normalizeDraft(snap.draft);
          state.template = clone(snap.template);
          state.selectionRaw = snap.selectionRaw;
          calls.push("restore:ok");
          return true;
        },
        resolveActiveTemplate: () => clone(state.template),
        template: TEMPLATE_A
      }, extra || {});
    }
  };
}

function incoming(options) {
  const opts = options || {};
  const draft = opts.draft || draftFixture("PQ-NEW", 2000000);
  return {
    draft,
    template: opts.template === undefined ? TEMPLATE_A : opts.template,
    expectedFingerprint: opts.expectedFingerprint === undefined
      ? Contract.contentFingerprint(draft, opts.template === undefined ? TEMPLATE_A : opts.template)
      : opts.expectedFingerprint
  };
}

/* ── 1. 정상 적용 ── */
{
  const e = editor();
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft,
    template: input.template,
    expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.ok, true, "NORMAL_APPLY_OK");
  assert.equal(result.applied, true, "NORMAL_APPLY_APPLIED");
  assert.equal(result.preserved, false, "NORMAL_APPLY_NOT_A_ROLLBACK");
  assert.equal(result.draft.meta.quoteNo, "PQ-NEW", "NORMAL_APPLY_NEW_DRAFT");
  assert.equal(e.calls.indexOf("restore:ok"), -1, "NORMAL_APPLY_NO_ROLLBACK");
}

/* ── 2. 승인 템플릿 불일치 → 변이 없음 ── */
{
  const e = editor();
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft,
    template: TEMPLATE_B,
    expectedFingerprint: Contract.contentFingerprint(input.draft, TEMPLATE_B)
  }));
  assert.equal(result.ok, false, "TEMPLATE_MISMATCH_REJECTED");
  assert.equal(result.code, "template_authority_mismatch", "TEMPLATE_MISMATCH_CODE");
  assert.equal(result.preserved, true, "TEMPLATE_MISMATCH_PRESERVED");
  assert.equal(e.calls.filter((c) => c.indexOf("write") === 0).length, 0, "TEMPLATE_MISMATCH_NO_WRITE");
  assert.equal(e.state.draft.meta.quoteNo, "PQ-OLD", "TEMPLATE_MISMATCH_OLD_DRAFT_INTACT");
}

/* ── 3. 내용 지문 사전 불일치 → 변이 없음 ── */
{
  const e = editor();
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft,
    template: TEMPLATE_A,
    expectedFingerprint: "fnv1a-deadbeef"
  }));
  assert.equal(result.code, "content_fingerprint_mismatch", "PREFLIGHT_FINGERPRINT_MISMATCH");
  assert.equal(result.preserved, true, "PREFLIGHT_FINGERPRINT_PRESERVED");
  assert.equal(e.calls.filter((c) => c.indexOf("write") === 0).length, 0, "PREFLIGHT_NO_WRITE");
}

/* ── 4. 지문 계산 불가 ── */
{
  const e = editor();
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks({ fingerprint: () => null }), {
    nextDraft: input.draft,
    template: TEMPLATE_A,
    expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.code, "fingerprint_unavailable", "FINGERPRINT_UNAVAILABLE");
  assert.equal(result.preserved, true, "FINGERPRINT_UNAVAILABLE_PRESERVED");
  assert.equal(e.calls.filter((c) => c.indexOf("write") === 0).length, 0, "FINGERPRINT_UNAVAILABLE_NO_WRITE");
}

/* ── 5. 잘못된 draft → 변이 없음 ── */
{
  const e = editor();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: { schemaVersion: 99 },
    template: TEMPLATE_A,
    expectedFingerprint: "x"
  }));
  assert.equal(result.code, "invalid_draft", "INVALID_DRAFT_REJECTED");
  assert.equal(result.preserved, true, "INVALID_DRAFT_PRESERVED");
  assert.equal(e.calls.filter((c) => c.indexOf("write") === 0).length, 0, "INVALID_DRAFT_NO_WRITE");
}

/* ── 6. replace 실패 반환 → 복구 ── */
{
  const e = editor({ writeMode: "fail" });
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.ok, false, "REPLACE_FAIL_REJECTED");
  assert.equal(result.code, "invalid_draft", "REPLACE_FAIL_CODE_SURFACED");
  assert.equal(result.restored, true, "REPLACE_FAIL_RESTORED");
  assert.equal(result.preserved, true, "REPLACE_FAIL_PRESERVED");
  assert.equal(e.state.draft.meta.quoteNo, "PQ-OLD", "REPLACE_FAIL_OLD_DRAFT_INTACT");
}

/* ── 7. 일부 변이 후 예외 → 복구 ── */
{
  const e = editor({ writeMode: "throwAfterPartial" });
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.code, "replace_exception", "PARTIAL_THEN_THROW_CODE");
  assert.equal(result.applied, false, "PARTIAL_THEN_THROW_NOT_APPLIED");
  assert.equal(result.restored, true, "PARTIAL_THEN_THROW_RESTORED");
  assert.equal(result.preserved, true, "PARTIAL_THEN_THROW_PRESERVED");
  assert.equal(e.state.draft.memo, "", "PARTIAL_MUTATION_ROLLED_BACK");
  assert.equal(e.state.draft.meta.quoteNo, "PQ-OLD", "PARTIAL_THEN_THROW_OLD_DRAFT_INTACT");
}

/* ── 8. 되읽기 불일치 → 복구 ── */
{
  const e = editor({ writeMode: "mismatch" });
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.code, "apply_verification_failed", "READBACK_MISMATCH_CODE");
  assert.equal(result.restored, true, "READBACK_MISMATCH_RESTORED");
  assert.equal(result.preserved, true, "READBACK_MISMATCH_PRESERVED");
  assert.equal(e.state.draft.memo, "", "READBACK_MISMATCH_ROLLED_BACK");
}

/* ── 9. 복구 실패 → 보존을 주장하지 않는다 ── */
{
  const e = editor({ writeMode: "mismatch", restoreFails: true });
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.ok, false, "ROLLBACK_FAILURE_NOT_OK");
  assert.equal(result.restored, false, "ROLLBACK_FAILURE_NOT_RESTORED");
  assert.equal(result.preserved, false, "ROLLBACK_FAILURE_NOT_CLAIMED");
}

/* ── 10. 복구 예외도 보존 주장 없음 ── */
{
  const e = editor({ writeMode: "mismatch", restoreThrows: true });
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.restored, false, "ROLLBACK_EXCEPTION_NOT_RESTORED");
  assert.equal(result.preserved, false, "ROLLBACK_EXCEPTION_NOT_CLAIMED");
}

/* ── 11. 기존 지문을 알 수 없으면 복구해도 보존을 주장하지 않는다 ── */
{
  const e = editor({ writeMode: "mismatch" });
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks({
    fingerprint: (value) => (value && value.meta && value.meta.quoteNo === "PQ-OLD" ? null
      : Contract.contentFingerprint(value, TEMPLATE_A))
  }), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.restored, true, "UNKNOWN_ORIGINAL_FINGERPRINT_RESTORED");
  assert.equal(result.preserved, false, "UNKNOWN_ORIGINAL_FINGERPRINT_NOT_CLAIMED");
}

/* ── 12. 적용 직전 가드 거부 → 변이 없음 ── */
{
  const e = editor();
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks({
    beforeApply: () => ({ ok: false, code: "drive_session_changed" })
  }), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.ok, false, "GUARD_REJECTED");
  assert.equal(result.code, "drive_session_changed", "GUARD_CODE_SURFACED");
  assert.equal(result.preserved, true, "GUARD_PRESERVED");
  assert.equal(e.calls.filter((c) => c.indexOf("write") === 0).length, 0, "GUARD_NO_WRITE");
  assert.equal(e.calls.indexOf("snapshot"), 0, "GUARD_AFTER_SNAPSHOT");
}

/* ── 13. 가드 예외도 안전하게 거부 ── */
{
  const e = editor();
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks({
    beforeApply: () => { throw new Error("guard exploded"); }
  }), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.code, "apply_guard_rejected", "GUARD_EXCEPTION_CODE");
  assert.equal(e.calls.filter((c) => c.indexOf("write") === 0).length, 0, "GUARD_EXCEPTION_NO_WRITE");
}

/* ── 14. 스냅샷 실패 → 아무것도 하지 않음 ── */
{
  const e = editor({ snapshotFails: true });
  const input = incoming();
  const result = Atomic.applyImport(Object.assign(e.hooks(), {
    nextDraft: input.draft, template: TEMPLATE_A, expectedFingerprint: input.expectedFingerprint
  }));
  assert.equal(result.code, "snapshot_unavailable", "SNAPSHOT_UNAVAILABLE");
  assert.equal(result.preserved, false, "SNAPSHOT_UNAVAILABLE_NOT_CLAIMED");
  assert.equal(e.calls.filter((c) => c.indexOf("write") === 0).length, 0, "SNAPSHOT_UNAVAILABLE_NO_WRITE");
}

/* ── 15. 훅 누락 → 헬퍼 없음 ── */
{
  const result = Atomic.applyImport({ nextDraft: draftFixture("PQ-NEW") });
  assert.equal(result.code, "import_helper_unavailable", "MISSING_HOOKS_CODE");
  assert.equal(result.preserved, false, "MISSING_HOOKS_NOT_CLAIMED");
}

/* ── 16. 템플릿 권위 비교는 savedSkillId + fingerprint 만 본다 ── */
{
  assert.equal(Atomic.sameTemplateAuthority(
    { savedSkillId: SKILL_A, fingerprint: "fp-a", label: "A" },
    { savedSkillId: SKILL_A, fingerprint: "fp-a", label: "다른 이름" }
  ), true, "TEMPLATE_AUTHORITY_IGNORES_LABEL");
  assert.equal(Atomic.sameTemplateAuthority(
    { savedSkillId: SKILL_A, fingerprint: "fp-a" },
    { savedSkillId: SKILL_A, fingerprint: "fp-b" }
  ), false, "TEMPLATE_AUTHORITY_COMPARES_FINGERPRINT");
  assert.equal(Atomic.sameTemplateAuthority(
    { savedSkillId: SKILL_A, fingerprint: "fp-a" },
    { savedSkillId: SKILL_A }
  ), false, "TEMPLATE_AUTHORITY_REQUIRES_FINGERPRINT");
  assert.equal(Atomic.sameTemplateAuthority(null, TEMPLATE_A), false, "TEMPLATE_AUTHORITY_REQUIRES_BOTH");
}

console.log("B66_IMPORT_ATOMIC=PASS");
console.log("NORMAL_APPLY=PASS");
console.log("TEMPLATE_MISMATCH_NO_MUTATION=PASS");
console.log("PREFLIGHT_FINGERPRINT_NO_MUTATION=PASS");
console.log("FINGERPRINT_UNAVAILABLE_NO_MUTATION=PASS");
console.log("INVALID_DRAFT_NO_MUTATION=PASS");
console.log("REPLACE_FAILURE_ROLLBACK=PASS");
console.log("PARTIAL_MUTATION_THEN_THROW_ROLLBACK=PASS");
console.log("READBACK_MISMATCH_ROLLBACK=PASS");
console.log("ROLLBACK_FAILURE_NEVER_CLAIMS_PRESERVATION=PASS");
console.log("UNKNOWN_ORIGINAL_FINGERPRINT_NEVER_CLAIMS_PRESERVATION=PASS");
console.log("COMMIT_POINT_GUARD=PASS");
console.log("SNAPSHOT_REQUIRED=PASS");
console.log("MISSING_HOOKS_FAIL_CLOSED=PASS");
