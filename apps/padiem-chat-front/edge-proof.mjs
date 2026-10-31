// Sign only the WebSocket route supported by COM2 EdgeProofVerifier.
const PATH = "/api/claw/connector/gateway/session";
const PROOF_HEADERS = ["x-padiem-edge-at", "x-padiem-edge-id", "x-padiem-edge-tls", "x-padiem-edge-proof"];

export async function signedRequestHeaders(request, secret, { now = () => Date.now(), random = () => crypto.randomUUID().replaceAll("-", "") } = {}) {
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/") || request.method.includes("\n") || url.pathname.includes("\n")) throw new Error("unsupported_edge_proof_request");
  if (typeof secret !== "string" || secret.length < 32) throw new Error("edge_proof_secret_missing");
  const tls = request.cf?.tlsVersion;
  if (tls !== "TLSv1.2" && tls !== "TLSv1.3") throw new Error("edge_proof_tls_unavailable");
  const id = random();
  if (!/^[0-9a-f]{32,64}$/.test(id)) throw new Error("invalid_edge_request_id");
  const at = String(Math.floor(now() / 1000));
  const signed = ["v1", request.method, url.pathname, at, id, tls].join("\n");
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const bytes = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(signed)));
  const proof = "v1=" + Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  const headers = new Headers(request.headers);
  for (const name of PROOF_HEADERS) headers.delete(name);
  headers.set("x-padiem-edge-at", at);
  headers.set("x-padiem-edge-id", id);
  headers.set("x-padiem-edge-tls", tls);
  headers.set("x-padiem-edge-proof", proof);
  return headers;
}
