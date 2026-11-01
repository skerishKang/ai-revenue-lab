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

const approvalPendingOnly = {
  ok: true, contract_version: "claw-web-xlsx-selection.v1",
  p01_approval_started: false, processing_started: false,
  workcopy_created: false, drive_uploaded: false,
  selection: {
    selection_ref: "sel_" + "c".repeat(32),
    document_id: row.document_id, filename: row.filename,
    size_bytes: row.size_bytes, source_sha256: row.source_sha256,
    status: "source_selected_p01_not_started",
    p01_approval_started: false, processing_started: false,
  },
};
assert.equal(office.validateSelection(approvalPendingOnly, row), true);
assert.equal(office.validateSelection({
  ...approvalPendingOnly, p01_approval_started: true,
}, row), false);
assert.equal(office.validateSelection({
  ...approvalPendingOnly, selection: {...approvalPendingOnly.selection, source_sha256: "f".repeat(64)},
}, row), false);
assert.equal(office.validateSelection({
  ...approvalPendingOnly, selection: {...approvalPendingOnly.selection, status: "approved"},
}, row), false);

// 1 GiB originals: above the shared 10 MB split the browser uses the lane.
const laneRow = { ...row, size_bytes: office.INLINE_MAX_BYTES + 1, file_id: "file_" + "d".repeat(32) };
assert.equal(office.validFile(laneRow), true);
assert.equal(office.validFile({ ...laneRow, file_id: "file_foreign" }), false);
assert.equal(office.validFile({ ...row, file_id: 7 }), false);
assert.equal(office.shouldUseFileLane(office.INLINE_MAX_BYTES), false);
assert.equal(office.shouldUseFileLane(office.INLINE_MAX_BYTES + 1), true);
assert.equal(office.shouldUseFileLane(1024 * 1024 * 1024), true);
assert.equal(office.shouldUseFileLane(1024 * 1024 * 1024 + 1), false);
assert.equal(office.shouldUseFileLane(0), false);
assert.equal(office.shouldUseFileLane(1.5), false);
console.log("web XLSX 1 GiB lane contract: PASS");
