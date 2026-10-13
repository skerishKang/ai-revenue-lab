// #4139: dedicated, short-lived Cloudflare Python edge WSS probe only.
// No owner, device, session or customer data. Must never target production.
const name = process.env.PADIEM_EDGE_CANARY_NAME;
const subdomain = process.env.PADIEM_EDGE_CANARY_SUBDOMAIN;
if (typeof name !== "string" ||
    !/^padiem-conn-py-e-[0-9]{8,14}-[0-9]{1,3}$/.test(name) ||
    typeof subdomain !== "string" ||
    !/^[a-z0-9][a-z0-9-]{0,62}$/.test(subdomain) ||
    typeof WebSocket !== "function") {
  console.error("CONNECTOR_CANARY_WSS_INPUT=FAIL");
  process.exit(2);
}
// Subdomain is parsed from the actual Wrangler deployment output, not
// invented from the local operator account or user-controlled requests.
const url = `wss://${name}.${subdomain}.workers.dev/__padiem_canary/wss`;
const outcome = await new Promise((resolve) => {
  let settled = false;
  let stage = 0;
  const ws = new WebSocket(url);
  const deadline = setTimeout(() => done(false, "bounded_timeout"), 12000);
  function done(ok, reason) {
    if (settled) return;
    settled = true;
    clearTimeout(deadline);
    try { ws.close(); } catch {}
    resolve({ok, reason});
  }
  ws.addEventListener("error", (event) => {
    // Emit only HTTP status class/code from a failed handshake. Never echo
    // raw URL, headers, tokens, exception messages or stack traces.
    const detail = String(event?.error?.message ?? event?.message ?? "");
    const match = detail.match(/(?:status|response|unexpected server)[^0-9]*(4[0-9]{2}|5[0-9]{2})/i);
    done(false, match ? "handshake_http_" + match[1] : "wss_transport_error");
  });
  ws.addEventListener("close", () => {
    if (!settled) done(false, "early_close");
  });
  ws.addEventListener("message", ({data}) => {
    if (stage === 0 && data === "PADIEM_CANARY_OPEN") {
      stage = 1;
      ws.send("PADIEM_CANARY_NO_SECRET_PING");
    } else if (stage === 1 && data === "PADIEM_CANARY_PONG") {
      done(true, "python_sdk_edge_101_bidirectional_frames");
    } else {
      done(false, "unexpected_frame");
    }
  });
});
console.log(JSON.stringify({
  contract:"padiem.connector.external-python-sdk-wss.v1",
  edge_wss_frame_roundtrip:outcome.ok,
  reason:outcome.reason,
  customer_data_used:false,
}));
if (!outcome.ok) process.exitCode=1;
