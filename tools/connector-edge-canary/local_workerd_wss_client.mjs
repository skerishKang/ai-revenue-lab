// #4139 CI-only local Workerd Python ASGI transport exercise.
// Never contact any public URL or send device/owner data.
const target = "ws://127.0.0.1:8800/__padiem_canary/wss";
if (process.argv.length !== 2 || typeof WebSocket !== "function") {
  console.error("CONNECTOR_CANARY_LOCAL_WSS_INVALID_INPUT");
  process.exit(2);
}
const result = await new Promise((resolve) => {
  let stage = 0;
  let scheme = null;
  let rawPath = null;
  let query = null;
  let complete = false;
  const socket = new WebSocket(target);
  const timeout = setTimeout(() => done(false, "timeout"), 9000);
  function done(ok, reason) {
    if (complete) return;
    complete = true;
    clearTimeout(timeout);
    try { socket.close(); } catch {}
    resolve({ok, reason, scheme, rawPath, query});
  }
  socket.addEventListener("error", () => done(false, "transport_error"));
  socket.addEventListener("close", () => {
    if (!complete) done(false, "early_close");
  });
  socket.addEventListener("message", ({data}) => {
    if (stage === 0 && typeof data === "string"
        && data.startsWith("PADIEM_CANARY_SCHEME_")) {
      scheme = data.slice("PADIEM_CANARY_SCHEME_".length);
      stage = 1;
    } else if (stage === 1 && typeof data === "string"
        && data.startsWith("PADIEM_CANARY_RAW_")) {
      rawPath = data.slice("PADIEM_CANARY_RAW_".length);
      stage = 2;
    } else if (stage === 2 && typeof data === "string"
        && data.startsWith("PADIEM_CANARY_QUERY_")) {
      query = data.slice("PADIEM_CANARY_QUERY_".length);
      stage = 3;
    } else if (stage === 3 && data === "PADIEM_CANARY_OPEN") {
      stage = 4;
      socket.send("PADIEM_CANARY_NO_SECRET_PING");
    } else if (stage === 4 && data === "PADIEM_CANARY_PONG") {
      done(true, "asgi_101_text_roundtrip");
    } else {
      done(false, "unexpected_frame");
    }
  });
});
console.log(JSON.stringify({
  contract:"padiem.canary.local-python-sdk-wss.v1",
  real_workerd_asgi_roundtrip:result.ok,
  scope:"local_only_no_edge_tls_no_device_auth",
  reason:result.reason,
  asgi_scope_scheme:result.scheme,
  asgi_raw_path_status:result.rawPath,
  asgi_query_string_status:result.query
}));
// For local ws://, Cloudflare's Python ASGI adapter reports the *HTTP*
// transport URL scheme. This MUST NOT be mistaken for a verified edge TLS
// connection: only the production Worker may independently prove request.cf.
if (result.scheme !== "http") {
  console.error("CONNECTOR_CANARY_LOCAL_ASGI_SCHEME_DRIFT=FAIL");
  process.exitCode = 1;
} else {
  console.log("CONNECTOR_CANARY_LOCAL_ASGI_HTTP_SCHEME=PASS");
}
if (!result.ok) process.exitCode = 1;
