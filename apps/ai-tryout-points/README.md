# B65 AI Tryout Points

B65 is a distinct side-income product for rewards earned after a provider-verified AI product tryout or quality-check action is completed.

## Product boundary

- **B64 AI Reward Router:** rewarded ad, click, visit, and later earning-route discovery.
- **B65 AI Tryout Points:** points earned only after a provider-signed action-completion event.
- A click or page visit is never a B65 completion authority.
- Provider secrets, keys, payout execution, Production deployment, and live reward balances are outside this foundation slice.

## Current implementation

- typed tryout offer and immutable reward value contracts;
- HMAC-SHA256 completion callback verification with constant-time comparison, separate maximum age and maximum future-skew bounds, and fail-closed rejection of unknown algorithm or version;
- completion, duplicate, duplicate-reversal, replay, reversal, identity/value mismatch, stale, clock-skew, and budget fail-closed rules;
- explicit record key `(providerId, offerId, providerTransactionId)` and a separate provider+nonce replay key, with a bounded `observedNonces` list per record so a nonce first seen on a duplicate completion or a reversal is still bound to that transaction, and reuse for another transaction is rejected;
- server-owned `firstObservedAt`/`lastObservedAt` timestamps, with the provider's `occurredAt` stored separately under a documented 24h maximum clock skew; an explicit `maxProviderClockSkewMs` may only narrow that window, an over-large bound fails closed, and backdated duplicate/reversal observation is rejected rather than written as self-contradictory history;
- an explicit append-only audit flag that is set only for authenticated, meaningful transitions and conflicts;
- identifier validation that rejects whitespace-padded values rather than normalizing them, and rejects all ASCII/Unicode control characters so composite keys cannot collide;
- full validation of the supplied authoritative ledger history before any event, offer, replay, usage, duplicate, or reversal decision: a malformed record, duplicate record key, duplicate nonce owner, or throwing history accessor is `REJECT_INVALID_LEDGER_HISTORY` with a zero delta, no writable `next`, and no audit append, and one invalid record can never be masked by valid siblings;
- a single shared record validator/snapshotter (`isValidLedgerRecord`, `snapshotLedgerRecord`) and checked safe-integer summation (`safeSumMinor`, `safeAddMinor`) used by both the completion and claim paths, so a malformed reward amount, identifier, currency, state, timestamp, or `observedNonces` history, and any historical aggregate that leaves the safe-integer range, fails closed on both paths; caller-owned records are consumed once as frozen snapshots, and a new transition that alone would overflow is separately `REJECT_AMOUNT_OVERFLOW`;
- a fail-closed, source-only `assessPointsClaim` gate that rejects malformed input records and unsafe sums, computes independently available non-reversed amount, and always refuses payout with a truthful `SOURCE_ONLY_PAYOUT_DISABLED` block reason;
- allowlisted safe projections that cannot carry a secret, signature, raw provider payload, or internal nonce;
- Node.js built-in test suite with no runtime dependency.

## Durable caller obligation

The ledger and claim functions are pure source with no persistence. Two caller obligations are load-bearing for the guarantees they claim:

- **Pass complete authoritative append-only history.** Replay detection, budget and per-user limits, and the claim's available amount all read the `records` array passed in. A partial, filtered, paginated, or reconstructed history silently weakens every guarantee. The array is also validated in full before any decision: an invalid record is rejected as `REJECT_INVALID_LEDGER_HISTORY` rather than absorbed.
- **Enforce one reward per completion with durable unique keys inside a transaction.** The duplicate and replay checks are pure functions over an in-memory array, not a uniqueness constraint. Exactly-once crediting requires the caller to enforce unique `(providerId, offerId, providerTransactionId)` and unique `(providerId, nonce)` in a database transaction, so two concurrent callbacks cannot both observe an absent record and both credit.

## Remaining gates

This is a source-only foundation with no runtime dependency beyond the Node.js standard library. `payoutAllowed` is hard-wired to `false` and the default claim state is non-live. Still required before real points or payouts exist: durable storage for the ledger, nonce history, and audit log; an approved provider integration with key management and reconciliation; a payment rail; balance custody; and operational, compliance, and owner-authorization review. See `PRODUCT_CONTRACT.md` for the exact semantics and the full gate list.

The current state is technical foundation only. It does not expose real offers or claim real income.
