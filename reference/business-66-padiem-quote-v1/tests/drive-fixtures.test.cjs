"use strict";

const assert = require("node:assert/strict");
const Fixtures = require("./drive-fixtures.cjs");

assert.equal(Fixtures.CLIENT_ID, "test-client-id.apps.googleusercontent.com");
assert.equal(Fixtures.SKILL_ID, "b66skill_2eb55d822407f626b7a75c8c88d32c40");
assert.deepEqual(Fixtures.templateReference(), {
  savedSkillId: Fixtures.SKILL_ID, fingerprint: "fp-cgi-v1"
});
assert.deepEqual(Fixtures.approvedTemplates(), [{
  savedSkillId: Fixtures.SKILL_ID, fingerprint: "fp-cgi-v1",
  approved: true, active: true
}]);
assert.deepEqual(Fixtures.approvedTemplates({ label: "CGI" }), [{
  savedSkillId: Fixtures.SKILL_ID, fingerprint: "fp-cgi-v1",
  approved: true, active: true, label: "CGI"
}]);

// No accidental state leakage between test files / negative scenarios.
const first = Fixtures.approvedTemplates();
first[0].active = false;
const second = Fixtures.approvedTemplates();
assert.equal(second[0].active, true);
assert.notEqual(first, second);
assert.notEqual(first[0], second[0]);
const templateA = Fixtures.templateReference();
templateA.fingerprint = "replaced";
assert.equal(Fixtures.templateReference().fingerprint, "fp-cgi-v1");

const pdfA = Fixtures.pdfBytes(77);
const pdfB = Fixtures.pdfBytes();
assert.equal(pdfA.length, 512);
assert.deepEqual(Array.from(pdfA.slice(0, 5)), [37, 80, 68, 70, 45]);
assert.equal(pdfA[400], 77);
assert.equal(pdfB[400], 0);
pdfA[0] = 0;
assert.equal(pdfB[0], 37);

console.log("B66_SYNTHETIC_DRIVE_FIXTURES=PASS");
