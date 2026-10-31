# COM2 Chat edge proof

The COM2 host opts in with `PADIEM_COM2_EDGE_PROOF_REQUIRED` and reads
`PADIEM_COM2_EDGE_SECRET_FILE` and `PADIEM_COM2_EDGE_REPLAY_DB`. The
front Worker requires the corresponding secret `PADIEM_COM2_EDGE_SECRET`.
Provisioning and enabling them are separate operational actions.

When enabled, all HTTP and WebSocket requests, including `/health`, require
a proof. There is no loopback health exemption: direct health monitors need
a signed request before this mode can be enabled. Missing proof fails closed.
The existing v1 proof binds method, path, timestamp, request ID and observed
TLS version; it does not bind the query string or request body. TLS transport
to the tunnel remains required. Request IDs are recorded in the durable
replay database.

The connector WebSocket consumes the same verified request without a second
replay check. When the mode is off, the existing host behavior is unchanged.
