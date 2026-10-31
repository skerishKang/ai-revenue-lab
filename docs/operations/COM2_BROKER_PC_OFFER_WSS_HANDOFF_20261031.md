# COM2 broker PC-offer WSS — implementation and remaining validation

The default-off COM2 broker app route composes the existing `LivePcWssOffer`
and `CanonicalBrokerPendingPcLiveRPC` on the same BrokerComposition and SQLite
storage. It permits only local peers, rejects browser authorization headers
and requires a v1 service HMAC binding GET, path, timestamp and request ID.
The request ID is consumed in a durable SQLite replay ledger in the same
transaction before the WebSocket is accepted. This matches the proposed Chat
relay signature format. Session cap, disconnect cleanup and the original
default-off owner/scope/schema gates remain in force. No keys are generated.

The synthetic local-socket test exercises the actual broker app, real SQLite,
Ed25519 proof, owner reserve/delivery RPC, approved message, missing/invalid
service proof and replay rejection. A separate actor harness exercises
disconnect cleanup. These are not live Cloudflare, COM2, or device results.

Remaining: validate the Chat relay and broker together on the exact staged
revision; exercise concurrent replay, credential delivery and
authenticated installation ACK through the complete owner/Identity path. Check
service-secret file access and runtime dependency packaging on the staging host.
The schema-install and feature gates remain explicit operator decisions. The
private loopback HMAC contract and its shared-secret authority scope need review
before activation. This source change installs or starts no service.
