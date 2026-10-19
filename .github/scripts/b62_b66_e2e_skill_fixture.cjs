#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const B66 = path.join(ROOT, "reference", "business-66-padiem-quote-v1");
const Template = require(path.join(B66, "quote-template.js"));
const Skill = require(path.join(B66, "quote-skill.js"));

const OUTPUT = process.argv[2];
if (!OUTPUT) {
  console.error("usage: b62_b66_e2e_skill_fixture.cjs <output.json>");
  process.exit(2);
}

const NOW = "2026-10-01T00:00:00.000Z";
const base = {
  id: "b66-e2e-canonical-v1",
  name: "B66 E2E 견적서",
  fixedDefaults: {
    sender: {
      company: "파디엠 테스트 공급자",
      rep: "테스트 담당",
      bizNo: "",
      address: "대한민국",
      phone: "",
      email: "",
      presetId: "b66-e2e"
    },
    validDays: 30,
    taxMode: "EXCLUSIVE",
    memo: "B66 Production E2E 전용 합성 견적서"
  },
  variableSchema: {
    recipient: true,
    quoteNo: true,
    issueDate: true,
    items: true,
    memo: true,
    taxMode: true
  },
  internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
  provenance: {
    sourceKind: "sample",
    sourceName: "b66-e2e-synthetic",
    sourceRef: "issue-3347",
    capturedAt: NOW,
    warnings: [],
    unknowns: [],
    evidence: [{ label: "purpose", value: "production-e2e" }]
  },
  approval: null,
  createdAt: NOW,
  updatedAt: NOW
};

const unapproved = Skill.buildSkill(base);
if (!unapproved || unapproved.approved !== false || !unapproved.fingerprint) {
  throw new Error("canonical unapproved Skill build failed");
}

const approved = Skill.buildSkill({
  ...base,
  approval: {
    schemaVersion: Skill.SKILL_APPROVAL_SCHEMA_VERSION,
    status: "approved",
    skillFingerprint: unapproved.fingerprint,
    approvedBy: "operator:central",
    approvedAt: NOW,
    approvalRef: "issue-3347"
  }
});
if (!approved || approved.approved !== true) {
  throw new Error("canonical approved Skill build failed");
}
const compiled = Skill.compileSkill(approved);
if (!compiled.ok) {
  throw new Error("canonical approved Skill compile failed");
}
if (
  compiled.compiled.executionContract.structuredRepeatGenerationModelCalls !== 0 ||
  compiled.compiled.executionContract.sourceDocumentReanalysisPerRepeat !== 0 ||
  compiled.compiled.executionContract.fullDocumentAiRegenerationPerRepeat !== 0
) {
  throw new Error("repeat-generation zero-call contract drifted");
}

const serialized = Skill.serializeSkill(approved);
fs.writeFileSync(OUTPUT, JSON.stringify(serialized), { encoding: "utf8", flag: "wx" });
console.log("B62_B66_E2E_CANONICAL_SKILL_FIXTURE=PASS");
console.log("STRUCTURED_REPEAT_GENERATION_MODEL_CALLS=0");
console.log("SOURCE_DOCUMENT_REANALYSIS_PER_REPEAT=0");
console.log("FULL_DOCUMENT_AI_REGENERATION_PER_REPEAT=0");
console.log("RAW_SKILL_OUTPUT=0");
