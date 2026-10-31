# COM2 broker PC-offer WSS — partial test and remaining integration

This is a **test harness, not a mounted broker service route**. The test runs
the existing `LivePcWssOffer` and `CanonicalBrokerPendingPcLiveRPC` over
the COM2 SQLite adapter and a real loopback WebSocket, with real synthetic
Ed25519 sign/verify. It covers pc_offer_begin, nonce challenge, proof,
pc_offer_ready and disconnection cleanup. It does not use a real PC, Worker,
production identity, protected store or secret.

The production route `route_private_pc_wss_upgrade` delegates to the same
Broker DO instance that owns both the socket actor registry and owner approval
RPC methods. COM2 `BrokerComposition` currently has no
`CanonicalBrokerPendingPcLiveRPC` mixin, private owner RPC allowlist,
WebSocket route or ASGI adapter. Tests alone cannot close that gap.

Remaining before an operable route PR:

1. Define and review a private loopback upgrade authentication contract,
   replay handling and edge/Chat handoff. Do not accept unsigned public headers
   or treat loopback alone as device authentication.
2. Compose the existing actor into the **same** `BrokerComposition` and
   SQLite instance as its bounded owner approval/claim/delivery RPCs; preserve
   all default-off release/schema gates and connection limits. Ensure
   disconnection, restart, failures and one-use CAS fail closed.
3. Provide a CPython Ed25519 verifier and pinned service runtime dependency;
   the current broker runtime requirements do not provide cryptography. Test
   invalid proof, race, missing/replayed service authentication, and install
   ACK/owner RPC behavior through the real HTTP and socket app.
4. Replace the test harness with a test of the mounted default-off service
   route and verify Chat's real pc_offer_begin flow end to end; see
   CHAT_COM2_WSS_PARITY_FINDINGS_20261031.md in the separate parity PR.

No operational service was changed or started. Do not use this harness as a
production or staging endpoint.
