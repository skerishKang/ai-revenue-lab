import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { signedRequestHeaders } from "../edge-proof.mjs";

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const path = "/api/claw/connector/gateway/session";
const secret = "synthetic-only-secret-0123456789";
const id = "0123456789abcdef0123456789abcdef";
const options = { now: () => 1700000000000, random: () => id };
function request(url = "https://chat.padiem.net" + path) {
  const req = new Request(url, { headers: { "x-padiem-edge-proof": "forged", "x-padiem-edge-id": "forged" } });
  req.cf = { tlsVersion: "TLSv1.3" };
  return req;
}

test("signer replaces all attacker headers with deterministic verifier-compatible proof", async () => {
  const headers = await signedRequestHeaders(request(), secret, options);
  assert.equal(headers.get("x-padiem-edge-id"), id);
  assert.equal(headers.get("x-padiem-edge-at"), "1700000000");
  assert.equal(headers.get("x-padiem-edge-tls"), "TLSv1.3");
  assert.equal(headers.get("x-padiem-edge-proof"), "v1=ae41f2e13728a2ac4013ac7864e2621f96cf202f13a5fee3ceb79001d36ced0a");
});

test("missing TLS or key fails closed", async () => {
  const bad = request();
  bad.cf = {};
  await assert.rejects(signedRequestHeaders(bad, secret, options));
  await assert.rejects(signedRequestHeaders(request(), "short", options));
});
