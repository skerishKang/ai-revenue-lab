# Broker COM2 gap table (2026-10-31)

Scope: broker Stage 2-C at main 094d9430f. These classifications concern implementation and evidence, not production readiness. DO = Cloudflare Durable Object.

| Requirement | Status | COM2 broker evidence | DO / differential evidence and gap |
|---|---|---|---|
| Session validation | PARTIAL | apps/padiem-broker/service.py:182,185 delegate to shared runtime | packages/padiem-control-plane/local_agent_broker_worker.py:82,117 delegates to same runtime; apps/padiem-broker/tests/test_actual_do_parity.py compares real DO Python entrypoint and HTTP app using platform/storage doubles. Workerd and actual WebSocket remain untested. |
| Credential verification | PARTIAL | apps/padiem-broker/service.py:185,214; packages/padiem-control-plane/local_agent_broker_durable_runtime.py:644 | DO worker:76,117 shares runtime; wrong credential and rotation parity tested in test_actual_do_parity.py. Live-device verification remains. |
| Material purge | PARTIAL | shared runtime local_agent_broker_durable_runtime.py:151,155,163,379,387 | DO worker:76,79,109 uses shared runtime. test_actual_do_parity.py compares valid ACK deletion and invalid ACK retention on the actual DO Python class and broker HTTP, with Workers/storage doubles. Rotation and revoke parity and expired snapshot purge also covered. Live runtime remains unverified. |
| CAS races | PRESENT (local scope) | apps/padiem-broker/storage.py serializes shared connection transactions with a reentrant lock and BEGIN IMMEDIATE. | test_actual_do_parity.py runs simultaneous requests through the actual DO Python entrypoint and broker HTTP app; both yield one winner and one stale loser. It also races two real threads on one SQLite connection. Workers platform/storage remain doubles; live Workerd verification is excluded. |
| Pepper separation | PARTIAL | apps/padiem-broker/deploy/provision_secrets.sh:3; apps/padiem-broker/deploy/backup.py:6; service.py:100 accepts inline or file | Backup is DB-only and provisioning intends 0600 file; runtime also accepts inline value and actual deployment separation/permissions are not verified. Installed service preflight now requires an external non-symlink pepper file and checks POSIX private permissions; live deployment unverified. |
| 24h shadow comparison record | MISSING | apps/padiem-broker has no shadow runner or 24-hour discrepancy ledger | Existing test_differential_parity.py:143 is local synthetic comparison; no live 100% read-shadow result or 24-hour evidence. |

Counts: PRESENT 1 (local implementation/test scope) / PARTIAL 4 / MISSING 1. Earlier synthetic differential tests instantiate BrokerComposition on both sides (test_differential_parity.py:94); the new test exercises LocalAgentBrokerDurableObject with fake Workers base and storage. Neither is a running Cloudflare DO. Stage A/B deployment, production writes and live traffic are outside this PR.


## COM2 WebSocket and identity evidence (follow-up)

The COM2-only, default-off Chat host gateway verifies the edge HMAC and durable
replay ID before treating a loopback socket as WSS. Its private service-proof
RPC bindings are restricted to 127.0.0.1 ports 8799 (broker) and 8802 (identity)
and the pairing method allowlists. The edge signer is still a separate release
dependency: the trusted edge must strip client proof headers before signing.

A real loopback socket test exercises begin/finish, a disconnect, a
security-hold terminal close, and missing, forged and replayed proofs. It does
not establish a complete successful credential install or live-device pairing.
The identity differential suite now exercises the twelve allowed methods'
successful results as well as rejected envelopes against the DO class and the
COM2 SQLite-backed HTTP ingress. This is local test evidence; no live COM2
service, Cloudflare runtime, edge signer or real device was operated.
