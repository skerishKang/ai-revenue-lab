"""#4139: PC enrollment consent — pure contract core (LOCAL1), network-free.

Runs the ACTUAL exported core of ``claw-pc-enrollment-consent.js`` in a Node
``vm`` sandbox with a deferred DOM (``readyState = "loading"``), so the mount
path never executes. These assertions prove the wire contract is closed to
browser-supplied authority, that a stored consent can never become an ONLINE
claim or a P01 execution approval, and that the module owns no network call of
its own. No enrollment route, credential or pairing is exercised.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
CONSENT_JS = STATIC / "claw-pc-enrollment-consent.js"
SOURCE = CONSENT_JS.read_text(encoding="utf-8")

NODE = r"""
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = process.argv[1];
const src = fs.readFileSync(path.join(root, "claw-pc-enrollment-consent.js"), "utf8");

function assert(condition, label) { if (!condition) throw Error(label); }
function eq(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw Error(label + " :: " + JSON.stringify(actual) + " != " + JSON.stringify(expected));
}

// Deferred DOM: the IIFE registers install() but never runs it, so only the
// pure core + export execute.
const sandbox = {
  window: {},
  document: { readyState: "loading", addEventListener() {}, documentElement: { lang: "ko" } },
  Object, Array, Boolean, String, Error, JSON, console,
};
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const api = sandbox.window.PadiemClawPcEnrollmentConsent;
assert(api && typeof api === "object", "api exported");

// --- version + paths --------------------------------------------------------
eq(api.CONSENT_VERSION, "pc-enrollment-consent-v1", "consent version");
eq(api.GRANT_PATH, "/api/claw/connector/enrollments/consent/grant", "grant path");
eq(api.REVOKE_PATH, "/api/claw/connector/enrollments/consent/revoke", "revoke path");
eq(api.CONSENT_PRODUCT_ID, "b54-padiem-claw", "canonical product");

// --- grant/revoke bodies are closed field sets ------------------------------
const grant = api.buildGrantBody("pc-1");
eq(Object.keys(grant).sort(), ["confirmation_version", "confirmed", "device_id"], "grant fields");
eq(grant, { device_id: "pc-1", confirmed: true, confirmation_version: "pc-enrollment-consent-v1" }, "grant body");
for (const forbidden of ["owner", "owner_ref", "tenant", "tenant_id", "workspace", "workspace_ref",
                         "session", "session_id", "consent_id", "account_ref", "grants_read",
                         "grants_write", "dispatch_authorized", "subject_id"]) {
  assert(!(forbidden in grant), "grant must not carry " + forbidden);
}
const revoke = api.buildRevokeBody("consent-1");
eq(Object.keys(revoke).sort(), ["confirmation_version", "confirmed", "consent_id"], "revoke fields");
assert(!("device_id" in revoke), "revoke carries no device id");

// --- invalid identities are refused, never coerced --------------------------
for (const bad of [null, undefined, "", "has space", "a".repeat(129), 123, {}, [], "bad/slash"]) {
  assert(api.buildGrantBody(bad) === null, "grant rejects " + JSON.stringify(bad));
}
for (const bad of [null, undefined, "", "bad id", "a".repeat(129), 7]) {
  assert(api.buildRevokeBody(bad) === null, "revoke rejects " + JSON.stringify(bad));
}

// --- readiness requires every condition -------------------------------------
const full = { featureActivated: true, productId: "b54-padiem-claw", deviceId: "pc-1", acknowledged: true };
eq(api.consentReadiness(full), { ready: true, blocked: null }, "ready");
eq(api.consentReadiness({ ...full, featureActivated: false }).blocked, "consent_feature_not_active", "feature gate");
eq(api.consentReadiness({ ...full, productId: "" }).blocked, "consent_product_unknown", "product unknown");
eq(api.consentReadiness({ ...full, productId: "b66-quote" }).blocked, "consent_separate_product", "b66 separate");
eq(api.consentReadiness({ ...full, productId: "b62-chat" }).blocked, "consent_separate_product", "other product separate");
eq(api.consentReadiness({ ...full, deviceId: "" }).blocked, "consent_target_unknown", "target unknown");
eq(api.consentReadiness({ ...full, acknowledged: false }).blocked, "consent_not_acknowledged", "ack required");
eq(api.consentReadiness(undefined).blocked, "consent_feature_not_active", "no state fails closed");
eq(api.consentReadiness(null).blocked, "consent_feature_not_active", "null state fails closed");

// --- grant receipt: consent is never execution authority --------------------
eq(api.projectGrantReceipt(null, "pc-1"), { accepted: false, reason: "consent_receipt_invalid" }, "null receipt");
eq(api.projectGrantReceipt({ ok: false }, "pc-1"), { accepted: false, reason: "consent_receipt_invalid" }, "not ok");
eq(api.projectGrantReceipt({ ok: true, consent: { device_id: "pc-1", dispatch_authorized: true } }, "pc-1"),
   { accepted: false, reason: "consent_authority_escalation" }, "escalation refused");
eq(api.projectGrantReceipt({ ok: true, consent: { device_id: "other", dispatch_authorized: false } }, "pc-1"),
   { accepted: false, reason: "consent_receipt_mismatch" }, "device mismatch");
const okGrant = api.projectGrantReceipt(
  { ok: true, consent: { device_id: "pc-1", consent_id: "consent-1", dispatch_authorized: false } }, "pc-1");
assert(okGrant.accepted === true, "grant accepted");
eq(okGrant.state, "GRANTED", "grant state");
eq(okGrant.dispatchAuthorized, false, "never dispatch authorized");
eq(okGrant.online, false, "consent is never ONLINE");
eq(okGrant.consentId, "consent-1", "consent id projected");

// --- revoke receipt ---------------------------------------------------------
eq(api.projectRevokeReceipt({ ok: true, consent: { consent_id: "c1", dispatch_authorized: false } }, "c1").state,
   "REVOKED", "revoke state");
eq(api.projectRevokeReceipt({ ok: true, consent: { consent_id: "c1", dispatch_authorized: true } }, "c1"),
   { accepted: false, reason: "consent_authority_escalation" }, "revoke escalation refused");

// --- bounded error mapping --------------------------------------------------
eq(api.consentStateFromError(400, "connector_enrollment_explicit_consent_required").state, "DENIED", "denied");
eq(api.consentStateFromError(403, "enrollment_consent_withdrawn").state, "REVOKED", "withdrawn");
eq(api.consentStateFromError(400, "enrollment_consent_expired").state, "EXPIRED", "expired");
eq(api.consentStateFromError(500, "raw_upstream_thing").state, "FAILED", "unknown fails closed");
eq(api.consentStateFromError(401, "").state, "DENIED", "401 denied");

console.log("OK");
"""


def _node() -> str:
    found = shutil.which("node")
    if found:
        return found
    fallback = Path(r"C:\Users\limone\.workbuddy-ai\binaries\node\versions\22.22.2-6\node.exe")
    if fallback.exists():
        return str(fallback)
    pytest.skip("node runtime unavailable")


def test_pure_consent_contract_core():
    result = subprocess.run(
        [_node(), "-e", NODE, str(STATIC)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


def test_module_owns_no_network_call_and_is_default_off():
    # The only network path is a verified port; the module itself never fetches.
    assert "fetch(" not in SOURCE
    assert "XMLHttpRequest" not in SOURCE
    assert "navigator.sendBeacon" not in SOURCE
    # No markup injection path.
    assert "innerHTML" not in SOURCE
    assert "insertAdjacentHTML" not in SOURCE
    assert "outerHTML" not in SOURCE
    # Default OFF is explicit, and the confirm control starts disabled.
    assert "ack.checked = false" in SOURCE
    assert "confirm.disabled = true" in SOURCE
    # Only the reviewed, unmounted server paths are referenced.
    assert '"/api/claw/connector/enrollments/consent/grant"' in SOURCE
    assert '"/api/claw/connector/enrollments/consent/revoke"' in SOURCE


def test_no_read_write_or_execution_grant_is_ever_asserted():
    # The module must not construct any READ/WRITE/P01 grant or approval field.
    for forbidden in ("grants_read", "grants_write", "dispatch_authorized: true",
                      "dispatch_authorized:true", "raw_device_credential", "binding_ref"):
        assert forbidden not in SOURCE, forbidden
    # Consent is explicitly documented as distinct from execution approval.
    assert "CONSENT_AUTHORITY=NO" in SOURCE
    assert "NETWORK_WHEN_READY=NO" in SOURCE
