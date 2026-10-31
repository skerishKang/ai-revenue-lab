# Chat connector WSS parity work (2026-10-31)

On base dd348eeff the COM2 gateway rejected production's first
`pc_offer_begin` frame. The opt-in COM2 relay now forwards the frame to the
broker socket owner, rather than constructing another owner or store.
`test_com2_prod_wss_parity.py` sends the same synthetic first frame through
the production dispatch and COM2 route: both return the same challenge, with
the real `LivePcWssOffer` actor and a local SQLite adapter.

This first-frame test uses a transport double. It does not yet compare proof,
owner approval, credential/ACK, terminal result or close, and it does not
prove production parity or live device behavior. The relay is default off
(`PADIEM_COM2_PC_OFFER_RELAY_ENABLED`); enabling it requires the #6404
loopback broker socket endpoint and its durable replay protection. It sends a
new random request ID signed with the existing broker v1 service proof as the
GET body; the broker must verify and atomically consume it. The exact relay
contract and redirect/failure behavior need review before activation.
No Cloudflare Worker, live COM2 service or production state was changed.

## Local socket follow-up after #6400 and #6404

`test_com2_real_broker_socket_parity.py` starts the actual COM2 broker app on
loopback and the Chat relay behind the actual edge middleware. It compares a
direct broker connection using the shared production `LivePcWssOffer` actor
with the Chat-to-broker relay. Both reach challenge, Ed25519 verification,
ready, and owner-RPC approval. The edge proof uses a synthetic file; an
unsigned WebSocket is refused. SQLite and all service values are test-only.

This comparison is not a complete production-entrypoint differential. The
approval uses a synthetic challenge without a canonical issued pairing record;
the subsequent bootstrap is refused, so credential delivery, installation
ACK and successful terminal close remain unverified in this real-socket path.
A complete test must create the canonical pairing and Identity handoff state
using the existing test harness, then compare both complete paths. No actual
production data or deployed services were accessed.

The first real-socket run exposed a close-code mismatch on an invalid
post-approval bootstrap: the broker closed with 1008 while the relay returned
1000. The relay now forwards supported upstream close codes, and the focused
socket test confirms both paths return 1008 for this denial. This does not
establish parity for a successful pairing close.

## Canonical pairing and Identity handoff follow-up

`test_com2_real_pairing_bootstrap.py` installs a synthetic canonical pairing
and gateway schema in temporary SQLite. On actual local sockets, direct Broker
and the signed Chat relay both complete PC possession proof, owner delivery,
canonical pairing begin/finish, and authenticated `credential_fetch`.

The Identity handoff then refuses both COM2 paths. The broker route tracks the
live actor in `_com2_pc_sessions` (`apps/padiem-broker/pc_offer_asgi.py`), while
`broker_pending_pc_identity_handoff._actor` searches only
`_pending_pc_wss_by_id`. The pending-link map is consumed on delivery. The
focused test demonstrates `pending_pc_identity_live_proof_missing` with an
otherwise authenticated live actor. This is an observed host integration gap,
not evidence that an actual Cloudflare production pairing was tested.
Credential delivery, install ACK and paired-offline close remain unverified.

A prior grouped test run stopped after the first test. Its exact cause was not
captured and did not recur in three isolated, 25-second-bounded repetitions
(7 passed each). The in-process parity bridge now bounds its queue receive to
five seconds so a missing actor message cannot block that wait indefinitely.
