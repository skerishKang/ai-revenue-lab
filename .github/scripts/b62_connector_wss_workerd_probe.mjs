// #4139: Real Workerd WebSocket transport proof; NO production endpoint or
// credentials, NO browser profile, NO login. Built-in Node 22 WebSocket only.
const target = process.argv[2];
const expected = "ws://127.0.0.1:8795/api/claw/connector/gateway/session";
if (target !== expected || typeof WebSocket !== "function") {
  process.stderr.write("PADIEM_CONNECTOR_WORKER_WS_INPUT_INVALID\n");
  process.exit(2);
}
const outcome = await new Promise((resolve) => {
  const socket = new WebSocket(target);
  let stage = 0;
  let settled = false;
  const done = (ok, reason) => {
    if (settled) return;
    settled = true;
    clearTimeout(timeout);
    try { socket.close(); } catch { /* no credential/session to clean */ }
    resolve({ ok, reason });
  };
  const timeout = setTimeout(() => done(false, "bounded_timeout"), 9000);
  socket.addEventListener("error", () => done(false, "websocket_handshake_error"));
  socket.addEventListener("close", () => {
    if (!settled) done(false, "premature_close");
  });
  socket.addEventListener("message", (event) => {
    if (typeof event.data !== "string") {
      done(false, "non_text_frame");
      return;
    }
    if (stage === 0 && event.data === "PADIEM_CONNECTOR_ASGI_WS_OPEN") {
      stage = 1;
      socket.send("synthetic-frame-no-credential");
    } else if (stage === 1 && event.data === "PADIEM_CONNECTOR_ASGI_WS_REPLY") {
      done(true, "text_roundtrip_complete");
    } else {
      done(false, "unexpected_frame");
    }
  });
});
process.stdout.write(JSON.stringify({
  contract: "padiem.connector-asgi-workerd-nonproduction.v1",
  transport_101_and_text_roundtrip: outcome.ok,
  scope: "local_workerd_single_fixture_no_broker",
  reason: outcome.reason,
}) + "\n");
if (!outcome.ok) process.exitCode = 1;
