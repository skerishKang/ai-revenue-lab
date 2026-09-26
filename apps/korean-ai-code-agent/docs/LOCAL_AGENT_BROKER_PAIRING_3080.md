# Local Agent broker pairing — Issue #3080

Issue #3080 (immediately after the M2c broker authority work): give a desktop
Local Agent its first broker credential
through an authenticated, challenge-proof pairing redemption, then run the whole
admitted dispatch loop strictly outbound (long-poll), without any inbound
listener on the desktop.

## Roles

- Cloud pairing authority (`padiem_control_plane.local_agent_broker_pairing`):
  issues single-use challenges and verifies challenge proofs.
- Browser / signed-in cloud session: the only caller allowed to ask for a
  one-time pairing code, scoped to its authenticated account/workspace.
- Desktop agent (`kagent.local_agent_broker_pairing_client`): proves possession
  of the code over the pinned outbound HTTPS route and receives a broker
  credential exactly once.
- Binding and credential lifecycle stays exclusively with the canonical broker
  authority (`InMemoryLocalAgentBrokerAuthority` / `StateBackedLocalAgentBrokerAuthority`);
  no second credential verifier exists.

## Flow

```text
browser (signed-in, account+workspace scoped)
  POST /v1/broker/pairings/challenge {account_ref, workspace_ref, now, ttl_seconds}
  -> {ok, challenge, pairing_code, pairing_code_returned_once, proof_transcript}

user reads the one-time pairing code and types it into the desktop agent (out of band)

desktop (no broker credential yet)
  proof = HMAC-SHA256(pairing_code, "claw-local-agent-pairing-proof.v1\n<challenge_id>\n<device_id>")
  POST /v1/broker/pairings/redeem {challenge_id, device_id, proof_ref, now}
  -> {ok, enrollment, credential_b64, credential_returned_once}

desktop persists credential -> opens broker sessions -> polls -> admits -> executes -> acks
```

## ONLINE is a server projection (#3083 rule, not relaxed)

The merged #3083 desktop-shell contract
(`apps/padiem-desktop-shell/src/contract/device-lifecycle.ts`) refuses any
`-> ONLINE` transition whose trigger is not `server_projection`, and names
`#3080` as the owner of that canonical device truth. #3080 therefore owns the
same gate on the Python side, in
`kagent/local_agent_server_projection.py`:

```text
redeem
-> PAIRED_OFFLINE                       (redemption can never claim ONLINE)
-> canonical broker session opened      (server-owned issued_at/expires_at)
-> server-owned heartbeat acknowledged (server-owned last_seen_at)
-> server-backed ONLINE projection      (project_server_backed_online_binding)
-> dispatch
```

`LocalAgentBrokerEnrollment` intentionally exposes **no** local ONLINE helper.
Without a real session *and* a server heartbeat that correlates to that exact
session/credential generation, `project_server_backed_online_binding` fails
closed with `ContractError`, and the runtime assembly still refuses to execute a
`PAIRED_OFFLINE` binding.

## Trust decisions (pinned, not implied)

- The pairing code is **derived from the deployment pepper plus a per-challenge
  nonce**. Server-side verification recomputes it from the nonce, so no raw
  pairing secret is ever persisted — matching the broker rule that only
  pepper digests survive in state.
- The challenge is **consumed before the binding is registered**, so a replay
  can never mint a second binding from one code. A failed proof or a duplicate
  device never leaves a replayable challenge behind.
- Account/workspace scope on redemption always comes from the stored
  server-side challenge and from the trusted auth context. A redeeming device
  cannot self-assert those (any `account_ref`/`workspace_ref` in a redeem body
  is a closed-schema 400: the field names simply do not exist).
- The redeem route needs **no broker credential** — it is authenticated by the
  proof plus a trusted TLS attestation. An already-authenticated principal may
  only redeem its own `device_id`.
- Route constants on the desktop (`BrokerPairingHttpsOperation`) and on the
  cloud (`PAIRING_CHALLENGE_ROUTE` / `PAIRING_REDEEM_ROUTE`) are pinned equal by
  `test_local_agent_broker_pairing_cross_contract.py`, as are the HMAC-SHA256
  transcript and proof derivation byte-for-byte.

## Non-goals (explicitly *not* done here)

- No public edge envelope service for the pairing routes yet
  (`PUBLIC_PAIRING_EDGE_SERVICE_CONFIGURED = False`); the deployment adapter
  that exposes `/v1/broker/pairings/*` publicly is still future work.
- No durable pairing store (`DURABLE_PAIRING_STORE_CONFIGURED = False`, and
  `IN_MEMORY_COUNTS_AS_DURABLE = False`): pending pairing challenges are
  in-memory by design, while bindings are durable through the canonical broker
  authority.
- No challenge issuance from the desktop client (`CLIENT_CHALLENGE_AUTHORITY =
  False`): the code is minted only by the signed-in cloud session.
- No second replay/sequence/fingerprint authority anywhere: poll, material,
  admission and ack reuse the existing canonical authorities unchanged.
- No production configuration anywhere (`PRODUCTION_* = False`).
