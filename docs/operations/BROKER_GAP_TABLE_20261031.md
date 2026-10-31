# Broker COM2 gap table (2026-10-31)

Scope: broker Stage 2-C at main 094d9430f. These classifications concern implementation and evidence, not production readiness. DO = Cloudflare Durable Object.

| Requirement | Status | COM2 broker evidence | DO / differential evidence and gap |
|---|---|---|---|
| Session validation | PARTIAL | apps/padiem-broker/service.py:182,185 delegate to shared runtime | packages/padiem-control-plane/local_agent_broker_worker.py:82,117 delegates to same runtime; apps/padiem-broker/tests/test_actual_do_parity.py compares real DO Python entrypoint and HTTP app using platform/storage doubles. Workerd and actual WebSocket remain untested. |
| Credential verification | PARTIAL | apps/padiem-broker/service.py:185,214; packages/padiem-control-plane/local_agent_broker_durable_runtime.py:644 | DO worker:76,117 shares runtime; wrong credential and rotation parity tested in test_actual_do_parity.py. Live-device verification remains. |
| Material purge | PARTIAL | shared runtime local_agent_broker_durable_runtime.py:151,155,163,379,387 | DO worker:76,79,109 uses shared runtime. test_actual_do_parity.py compares valid ACK deletion and invalid ACK retention on the actual DO Python class and broker HTTP, with Workers/storage doubles. Rotation and revoke parity and expired snapshot purge also covered. Live runtime remains unverified. |
| CAS races | PRESENT (local scope) | apps/padiem-broker/storage.py serializes shared connection transactions with a reentrant lock and BEGIN IMMEDIATE. | test_actual_do_parity.py runs simultaneous requests through the actual DO Python entrypoint and broker HTTP app; both yield one winner and one stale loser. It also races two real threads on one SQLite connection. Workers platform/storage remain doubles; live Workerd verification is excluded. |
| Pepper separation | PARTIAL | apps/padiem-broker/deploy/provision_secrets.sh:3; apps/padiem-broker/deploy/backup.py:6; service.py:100 accepts inline or file | Backup is DB-only and provisioning intends 0600 file; runtime also accepts inline value and actual deployment separation/permissions are not verified. Installed service preflight now requires an external non-symlink pepper file and checks POSIX private permissions; live deployment unverified. |
| 24h shadow comparison record | PARTIAL | apps/padiem-broker/shadow_compare.py compares an explicit read-only allowlist and records only time, method, and outcome. | tests/test_shadow_compare.py exercises actual DO Python entrypoint and broker ASGI HTTP with synthetic fixtures. Adapters must be connected and record completeness established before any 100% or 24h claim. No live shadow operation. |

Counts: PRESENT 1 (local implementation/test scope) / PARTIAL 5 / MISSING 0. Shadow recorder is not yet wired into a caller or demonstrated over 24h. Earlier synthetic differential tests instantiate BrokerComposition on both sides (test_differential_parity.py:94); the new test exercises LocalAgentBrokerDurableObject with fake Workers base and storage. Neither is a running Cloudflare DO. Stage A/B deployment, production writes and live traffic are outside this PR.


## COM2 WebSocket and identity evidence (follow-up)

The COM2-only, default-off Chat host gateway verifies the edge HMAC and durable
replay ID before treating a loopback socket as WSS. Its private service-proof
RPC bindings are restricted to 127.0.0.1 ports 8799 (broker) and 8802 (identity)
and the pairing method allowlists. The edge signer is still a separate release
dependency: the trusted edge must strip client proof headers before signing.

Real loopback socket tests exercise begin/finish, a disconnect, a security-hold
terminal close, missing/forged/replayed edge proofs, and a successful synthetic
credential/ACK exchange ending paired_offline and normal close. Identity and
broker replies are test doubles; no real-device installation is established.
The identity differential suite now exercises the twelve allowed methods'
successful results as well as rejected envelopes against the DO class and the
COM2 SQLite-backed HTTP ingress. This is local test evidence; no live COM2
service, Cloudflare runtime, edge signer or real device was operated.


Host configuration is default off. A future staged activation must provide
`PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED=true`, the readable file paths
`PADIEM_COM2_EDGE_SECRET_FILE`, `PADIEM_COM2_IDENTITY_RPC_SECRET_FILE`,
`PADIEM_COM2_BROKER_RPC_SECRET_FILE`, and a durable writable
`PADIEM_COM2_EDGE_REPLAY_DB` under the Chat host data directory. Each secret
must match its respective peer and be kept separate. The staged host installer
includes the WebSocket backend and edge verifier module; installation and
service startup were not executed by this change.
