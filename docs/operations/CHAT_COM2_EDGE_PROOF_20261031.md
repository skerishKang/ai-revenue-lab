# COM2 Chat edge proof

The COM2 host opts in with `PADIEM_COM2_EDGE_PROOF_REQUIRED` and reads
`PADIEM_COM2_EDGE_SECRET_FILE` and `PADIEM_COM2_EDGE_REPLAY_DB`. The
front Worker requires the corresponding secret `PADIEM_COM2_EDGE_SECRET`.
Provisioning and enabling them are separate operational actions.

When enabled, all HTTP and WebSocket requests require proof except the exact
HTTP GET `/health` path. The exception is path-based, not loopback-based.
Every other request without proof fails closed.
The existing v1 proof binds method, path, timestamp, request ID and observed
TLS version; it does not bind the query string or request body. TLS transport
to the tunnel remains required. Request IDs are recorded in the durable
replay database.

The connector WebSocket consumes the same verified request without a second
replay check. When the mode is off, the existing host behavior is unchanged.

## Replay store durability

`PADIEM_EDGE_REPLAY_SYNC_MODE` chooses how the replay database commits. `full`
(unset, empty, or any unknown value) is the unchanged behavior: one connection
per request, rollback journal and `synchronous=FULL`, one fsync per signed
request. `normal` keeps one connection open for the process in WAL with
`synchronous=NORMAL` and takes that fsync off the request path; the per-request
`BEGIN IMMEDIATE` / `INSERT` / `COMMIT`, the unique request ID and the
one-verify-at-a-time order are unchanged, so a replayed proof is refused the
same way in both modes.

`normal` turns SQLite's automatic checkpoint off for that connection and takes a
`PASSIVE` checkpoint every 200 committed requests or 30 seconds, on a connection
of its own, so no signed request waits for one. The connection is opened lazily,
reopened once if it is lost, and closed at process exit.

The trade is the newest writes: an abrupt power loss (not a process crash) can
drop the last few commits, so a proof consumed seconds before the loss could be
accepted once after the restart. That exposure is bounded by the signature
lifetime — the 300 s window — not by the store. WAL needs the replay database on
a local disk; it already lives on the host's ext4 data directory. A mode change
is read at process start, and a store left in WAL returns to the rollback
journal the next time the host serves `full`.
