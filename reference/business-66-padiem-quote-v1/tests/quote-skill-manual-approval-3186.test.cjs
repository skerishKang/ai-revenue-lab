/* B66 #3186 — 승인 결과 envelope 의 교차 언어 계약.

   서버 운영자 승인(b66_saved_skill_candidate_review.py)은 후보 envelope 를
   승인된 Saved Quote Skill envelope 로 바꾸고, 그 결과가 B66 의 정식
   Skill authority(quote-skill.js normalizeSkill)를 통과해야만 저장된다.

   이 테스트는 그 변환을 **문서화된 계약대로** 재현해 JS authority 가 실제로
   받아들이는지 확인한다. 서버 코드를 복사하지 않고 계약만 고정한다. */

const assert = require("node:assert");
const Skill = require("../quote-skill.js");
const Manual = require("../quote-skill-manual.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const NOW = "2026-10-11T06:00:00.000Z";
const OPERATOR = "usr_operator1";
const GRANT_REF = "b66grant_" + "d".repeat(32);
/* 서버가 후보 digest 로부터 파생하는 id 형태(값 자체는 서버가 결정한다). */
const SERVER_SKILL_ID = "saved-quote-0123456789abcdef";

const entry = {
  name: "우리회사 견적서",
  sender: {
    company: "주식회사 파디엠", rep: "강혜림", bizNo: "123-45-67890",
    address: "광주광역시 남구", phone: "062-000-0000", email: "quote@example.com"
  },
  validDays: 30, taxMode: "EXCLUSIVE", memo: "기본 비고",
  variableFlags: { memo: true, taxMode: true }
};

/* 서버 리뷰어의 승인 변환 계약(문서화된 최소 단계). */
function applyServerApproval(candidate, options) {
  const payload = JSON.parse(JSON.stringify(candidate));
  delete payload.status;
  delete payload.candidateId;
  /* 후보 전용 선언 지문은 정식 Skill 키 집합에 없다. 서버가 반드시 제거한다. */
  delete payload.skillFingerprint;
  payload.id = options.skillId;
  payload.name = candidate.name;
  payload.fingerprint = candidate.skillFingerprint;
  payload.rendererContract = "quote-template-renderer.v1";
  payload.calculationAuthority = "quote-core";
  payload.approval = {
    schemaVersion: 1,
    status: "approved",
    skillFingerprint: candidate.skillFingerprint,
    approvedBy: options.approvedBy,
    approvedAt: options.approvedAt,
    approvalRef: options.approvalRef
  };
  if (!payload.createdAt) payload.createdAt = options.approvedAt;
  payload.updatedAt = options.approvedAt;
  return payload;
}

const built = Manual.buildManualCandidate(entry, { now: NOW });
check(built.ok, "후보를 만든다");
const candidate = built.candidate;
check(candidate.approval === undefined, "후보는 승인 상태가 아니다");
eq(candidate.status, "candidate", "후보 상태");

const approved = applyServerApproval(candidate, {
  skillId: SERVER_SKILL_ID,
  approvedBy: OPERATOR,
  approvedAt: NOW,
  approvalRef: GRANT_REF
});

const normalized = Skill.normalizeSkill(approved);
check(normalized !== null, "서버 승인 envelope 를 JS Skill authority 가 받아들인다");
eq(normalized.approved, true, "승인된 Skill 로 인식된다");
eq(normalized.id, SERVER_SKILL_ID, "서버가 정한 Skill id 가 보존된다");
eq(normalized.name, candidate.name, "이름이 보존된다");
eq(normalized.fingerprint, candidate.skillFingerprint, "지문은 후보의 계산 기준과 동일하다");
eq(normalized.approval.approvedBy, OPERATOR, "승인 주체는 서버가 정한 운영자다");
eq(normalized.approval.approvalRef, GRANT_REF, "승인 참조는 서버 grant 다");
eq(normalized.approval.approvedAt, NOW, "승인 시각이 보존된다");
eq(normalized.calculationAuthority, "quote-core", "계산 authority 는 QuoteCore 다");
eq(normalized.rendererContract, "quote-template-renderer.v1", "렌더 계약은 기존 renderer 다");

/* 직렬화 왕복도 같은 authority 를 통과해야 한다. */
const serialized = Skill.serializeSkill(normalized);
check(serialized !== null, "승인된 Skill 을 직렬화할 수 있다");
check(Skill.normalizeSkill(serialized) !== null, "직렬화 결과도 정식 Skill 이다");

/* 후보 전용 키를 남기면 authority 가 거부한다 — 서버가 제거해야 하는 이유. */
const keptFingerprintKey = applyServerApproval(candidate, {
  skillId: SERVER_SKILL_ID, approvedBy: OPERATOR, approvedAt: NOW, approvalRef: GRANT_REF
});
keptFingerprintKey.skillFingerprint = candidate.skillFingerprint;
eq(Skill.normalizeSkill(keptFingerprintKey), null, "후보 전용 지문 키가 남으면 거부된다");

const keptStatusKey = applyServerApproval(candidate, {
  skillId: SERVER_SKILL_ID, approvedBy: OPERATOR, approvedAt: NOW, approvalRef: GRANT_REF
});
keptStatusKey.status = "candidate";
eq(Skill.normalizeSkill(keptStatusKey), null, "후보 상태 키가 남으면 거부된다");

/* 승인 증거가 없거나 지문이 어긋나면 승인된 Skill 이 아니다.
   (normalizeSkill 은 미승인 Skill 객체는 받아들이되 approved=false 로 남긴다.
   저장 가능한 승인 artifact 인지는 #3301 store 의 canonicalize 가 판정한다.) */
const noApproval = applyServerApproval(candidate, {
  skillId: SERVER_SKILL_ID, approvedBy: OPERATOR, approvedAt: NOW, approvalRef: GRANT_REF
});
delete noApproval.approval;
const noApprovalSkill = Skill.normalizeSkill(noApproval);
check(noApprovalSkill !== null, "미승인 Skill 객체 자체는 정규화된다");
eq(noApprovalSkill.approved, false, "승인 증거가 없으면 승인된 Skill 이 아니다");

const mismatched = applyServerApproval(candidate, {
  skillId: SERVER_SKILL_ID, approvedBy: OPERATOR, approvedAt: NOW, approvalRef: GRANT_REF
});
mismatched.approval.skillFingerprint = "f".repeat(64);
const mismatchedSkill = Skill.normalizeSkill(mismatched);
check(mismatchedSkill !== null, "지문이 어긋난 객체도 정규화는 된다");
eq(mismatchedSkill.approved, false, "승인 지문이 다르면 승인으로 인정되지 않는다");
eq(mismatchedSkill.approval, null, "어긋난 승인 증거는 버려진다");

/* 검토 후 내용이 바뀌면 지문이 달라져 과거 승인이 재사용될 수 없다. */
const tampered = applyServerApproval(candidate, {
  skillId: SERVER_SKILL_ID, approvedBy: OPERATOR, approvedAt: NOW, approvalRef: GRANT_REF
});
tampered.fixedDefaults.sender.company = "다른회사";
eq(Skill.normalizeSkill(tampered), null, "승인 후 내용이 바뀐 후보는 기존 승인으로 활성화되지 않는다");

/* 서버 승인은 운영자 신원과 grant 참조를 그대로 담는다(브라우저가 정하지 않는다). */
check(/^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$/.test(OPERATOR), "운영자 신원은 승인 참조 형식이다");
check(/^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$/.test(GRANT_REF), "grant 참조는 승인 참조 형식이다");

console.log("B66_APPROVAL_ENVELOPE_CONTRACT=PASS");
console.log("SERVER_APPROVED_SKILL_ACCEPTED_BY_JS_AUTHORITY=YES");
console.log("CANDIDATE_ONLY_KEYS_DROPPED=YES");
console.log("APPROVAL_WITHOUT_EVIDENCE_REJECTED=YES");
console.log("TAMPERED_CANDIDATE_NOT_ACTIVATED=YES");
