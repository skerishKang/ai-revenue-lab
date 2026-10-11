"use strict";

// Synthetic B66 Drive fixtures ONLY. No credentials, real customer data or network calls.
// Return new values on every call: tests must never share mutable session/template state.
const CLIENT_ID = "test-client-id.apps.googleusercontent.com";
const SKILL_ID = "b66skill_2eb55d822407f626b7a75c8c88d32c40";
const TEMPLATE_FINGERPRINT = "fp-cgi-v1";

function templateReference() {
  return { savedSkillId: SKILL_ID, fingerprint: TEMPLATE_FINGERPRINT };
}

function approvedTemplates(options = {}) {
  const approved = {
    savedSkillId: SKILL_ID, fingerprint: TEMPLATE_FINGERPRINT,
    approved: true, active: true
  };
  if (Object.prototype.hasOwnProperty.call(options, "label")) {
    approved.label = options.label;
  }
  return [approved];
}

function pdfBytes(marker) {
  const bytes = new Uint8Array(512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  if (marker) bytes[400] = marker;
  return bytes;
}

module.exports = Object.freeze({
  CLIENT_ID,
  SKILL_ID,
  TEMPLATE_FINGERPRINT,
  templateReference,
  approvedTemplates,
  pdfBytes
});
