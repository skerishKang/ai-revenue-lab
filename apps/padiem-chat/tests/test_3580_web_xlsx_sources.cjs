"use strict";
// #3580: browser web-file metadata never becomes P01 approval or local PC path.
const assert = require("node:assert/strict");
const office = require("../static/claw-web-xlsx-sources.js");

const row = {
  document_id: "doc_" + "a".repeat(32),
  filename: "학교 견적서.xlsx",
  size_bytes: 7542,
  source_sha256: "b".repeat(64),
  original_immutable: true,
  processing_authorized: false,
  expires_at: "2026-10-12T00:00:00+00:00",
};
assert.equal(office.validFile(row), true);
assert.equal(office.validFile({ ...row, processing_authorized: true }), false);
assert.equal(office.validFile({ ...row, filename: "../secrets.xlsx" }), false);
assert.equal(office.validFile({ ...row, document_id: "doc_foreign" }), false);
assert.equal(office.validFile({ ...row, source_sha256: "not_sha256" }), false);
const listing = {
  ok: true, contract_version: "claw-web-xlsx-source.v1",
  source: "browser_upload", read_authorized_for_processing: false,
  requires_p01_for_processing: true, files: [row],
};
assert.deepEqual(office.validateListing(listing), [row]);
assert.equal(office.validateListing({ ...listing, read_authorized_for_processing: true }), null);
assert.equal(office.validateListing({ ...listing, files: [row, row] }), null);
assert.equal(office.validateListing({ ...listing, source: "local_pc" }), null);
assert.equal(office.validateListing({ ...listing, files: [{...row, original_immutable: false}] }), null);
console.log("web XLSX source browser contract: PASS");
