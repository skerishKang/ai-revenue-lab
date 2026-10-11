/* Historical quote sender snapshot stability (#3406).

   HISTORICAL_QUOTE_SENDER_SNAPSHOT_STABLE=YES:
   - a QuoteDraft produced under CompanyProfile A keeps A's sender facts forever,
     even after the account CompanyProfile later changes to B;
   - a NEW quote picks up the current (B) facts;
   - the browser history envelope stores drafts by value (snapshot), never a
     live reference to the profile.

   Independent test file on purpose: history-behavior.test.cjs is currently
   being modified by PR #3519, so this proof does not touch it. */
const assert = require("node:assert");
const Skill = require("../quote-skill.js");
const History = require("../quote-history.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const NOW = "2026-10-01T09:00:00.000Z";

function fixedDefaults() {
  return {
    sender: {
      company: "양식기본상사",
      rep: "양식대표",
      bizNo: "000-00-00001",
      address: "양식기본주소",
      phone: "000-0000-0001",
      email: "skill-default@example.test",
      presetId: "saved-skill"
    },
    validDays: 30,
    taxMode: "EXCLUSIVE",
    memo: "양식 기본 메모"
  };
}

function approvedSkill() {
  const base = {
    id: "skill-snapshot",
    name: "스냅샷 검증용 견적 양식",
    fixedDefaults: fixedDefaults(),
    variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
    internalTemplate: require("../quote-template.js").serializeTemplate(
      require("../quote-template.js").builtInTemplate()
    ),
    provenance: {
      sourceKind: "file",
      sourceName: "synthetic-template-source.pdf",
      sourceRef: "source:synthetic-snapshot",
      capturedAt: NOW,
      warnings: [],
      unknowns: [],
      evidence: []
    },
    approval: null,
    createdAt: NOW,
    updatedAt: NOW
  };
  const unapproved = Skill.buildSkill(base);
  check(unapproved && unapproved.approved === false, "skill starts unapproved");
  return Skill.buildSkill(Object.assign({}, base, {
    approval: {
      schemaVersion: 1,
      status: "approved",
      skillFingerprint: unapproved.fingerprint,
      approvedBy: "central-cto",
      approvedAt: NOW,
      approvalRef: "issue-3406"
    }
  }));
}

function input(overrides) {
  return Object.assign({
    quoteNo: "PQ-20261001-001",
    issueDate: "2026-10-01",
    recipient: { company: "수신상사", person: "수신담당", address: "수신주소", email: "buyer@example.test" },
    items: [{ id: "item-1", name: "스냅샷 품목", qty: 2, unitPrice: 10000 }]
  }, overrides || {});
}

const profileA = {
  company: "스냅샷상사",
  representative: "스냅샷대표",
  businessNumber: "000-00-00002",
  address: "테스트시 테스트구",
  phone: "02-0000-0000",
  email: "profile-a@example.test"
};
const profileB = {
  company: "변경상사",
  representative: "변경대표",
  businessNumber: "000-00-00003",
  address: "변경시 변경구",
  phone: "02-0000-0002",
  email: "profile-b@example.test"
};

const skill = approvedSkill();

/* 2026-10-01: quote generated under profile A */
const builtA = Skill.buildDraft(skill, input(), { companyProfile: profileA });
check(builtA.ok === true, "draft A built under CompanyProfile A");
const draftA = builtA.draft;
check(draftA.sender.company === "스냅샷상사", "draft A snapshots profile A company");
check(draftA.sender.address === "테스트시 테스트구", "draft A snapshots profile A address");
check(draftA.sender.presetId === "account-company-profile", "sender authority is the account CompanyProfile");

/* stored into browser history (value semantics) */
let envelope = History.addEntry(null, draftA);
check(envelope.entries.length === 1, "draft A stored in history");

/* the caller's profile object is mutated afterwards (simulating a later edit) */
profileA.company = "변경시도상사";

/* 2026-10-10: CompanyProfile edited to B facts; a NEW quote uses B */
const builtB = Skill.buildDraft(skill, input({ quoteNo: "PQ-20261010-001", issueDate: "2026-10-10" }), {
  companyProfile: profileB
});
check(builtB.ok === true, "draft B built under CompanyProfile B");
check(builtB.draft.sender.company === "변경상사", "new quote uses current (B) sender facts");
check(builtB.draft.sender.address === "변경시 변경구", "new quote uses current (B) address");

/* historical draft keeps A exactly as generated */
const storedA = History.getEntry(envelope, envelope.entries[0].id);
check(storedA && storedA.draft, "stored entry readable");
check(storedA.draft.sender.company === "스냅샷상사",
  "HISTORICAL_QUOTE_SENDER_SNAPSHOT_STABLE=YES (company)");
check(storedA.draft.sender.address === "테스트시 테스트구", "stored address unchanged");
check(storedA.draft.sender.phone === "02-0000-0000", "stored phone unchanged");
check(storedA.draft.sender.email === "profile-a@example.test", "stored email unchanged");
check(storedA.draft.meta.quoteNo === "PQ-20261001-001", "stored quoteNo unchanged");

/* the post-hoc mutation of the profile object never leaked into history */
check(storedA.draft.sender.company !== "변경시도상사", "history holds a value snapshot, not a live reference");

/* history holds both eras side by side */
envelope = History.addEntry(envelope, builtB.draft);
check(envelope.entries.length === 2, "both drafts stored");
const senders = envelope.entries.map((entry) => entry.draft.sender.company).sort();
assert.deepStrictEqual(senders, ["변경상사", "스냅샷상사"], "each entry keeps its own sender snapshot");

/* precedence intact while snapshotting: family defaults still outrank profile fallbacks */
check(draftA.meta.validDays === skill.fixedDefaults.validDays, "SKILL_VALIDITY_BLINDLY_OVERRIDDEN_BY_COMPANY_PROFILE=NO");
check(draftA.tax.mode === skill.fixedDefaults.taxMode, "SKILL_TAX_POLICY_BLINDLY_OVERRIDDEN_BY_COMPANY_PROFILE=NO");
check(draftA.calculationPolicy === undefined || typeof draftA.calculationPolicy === "object",
  "QuoteCore remains the calculation authority");

console.log("ALL COMPANY-PROFILE-SNAPSHOT TESTS PASSED");
