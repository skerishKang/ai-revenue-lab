# B65 AI Tryout Points — Product Contract

## Identity

- **Proposed Business:** B65
- **Stable slug:** `ai-tryout-points`
- **Canonical proposal issue:** #3063
- **Lifecycle:** incubation
- **Product promise:** help users earn points when an approved AI service tryout or quality-check action is independently verified as completed.

B65 is separate from B64. A B64 click, ad view, or visit cannot create a B65 reward.

## Reward authority

A reward may be settled only when all conditions are true:

1. the offer is active and not expired;
2. the provider callback is HMAC-SHA256 verified from the exact raw body;
3. the signed timestamp is inside the accepted freshness window and is not ahead of server time by more than the explicit future skew;
4. the event identifies an approved action-completion type, never click or visit;
5. provider, offer, user, amount, and currency match the current local transaction;
6. the provider transaction is new and not previously reversed;
7. per-user and funded-budget limits remain available;
8. the provider `occurredAt` is within the documented maximum provider-clock skew of the server `observedAt`;
9. the provider+nonce pair has not already been used for a different transaction.

Client state, localStorage, a page redirect, a button click, or a browser-generated completion claim is never settlement authority.

Identifiers are opaque. A whitespace-padded identifier is rejected, never trimmed, so two spellings can never collapse onto one record or nonce key. Every ASCII control character (including NUL and DEL), the C1 range, and the Unicode line/paragraph separators are also rejected, so an identifier can never be split, reordered, or merged by a composite key join.

## Ledger rules

- A completion creates exactly one positive ledger entry.
- A replay or duplicate creates no balance mutation.
- A reversal creates one negative entry and preserves the original completion.
- A reversed transaction cannot silently reopen.
- A duplicate `REVERSED` for an already-reversed record returns the existing reversed record as `next`, with a balance delta of `0` and no audit append.
- Amounts are integer minor units; floating-point money is forbidden.
- Provider-reported reward value may be confirmed by signed evidence but cannot silently change an offer.
- This slice creates points accounting evidence only. It does not create a transferable wallet, cash custody, or external payout order.

## Record identity and replay

- A record's key is `(providerId, offerId, providerTransactionId)`. The same provider transaction id under two different offers is two distinct records.
- Replay is keyed separately on `(providerId, nonce)`. Reusing a provider+nonce for a different offer or transaction id is `REJECT_NONCE_REPLAY`.
- An exact duplicate with the same provider+nonce and the same transaction remains idempotent, with a balance delta of `0` and no audit append.
- The nonce is retained in ledger history so replay is detectable after the fact.

### Observed-nonce history (bounded, source-only)

A single nonce field cannot soundly represent replay. A provider may re-issue a duplicate completion, or a reversal, under a nonce the ledger has never seen before. A record therefore carries both a canonical `nonce` (the first completion nonce, preserved across reversal) and `observedNonces`: the bounded, append-only list of every distinct provider+nonce identity observed for that transaction, always starting with `nonce`.

- A newly observed nonce on a duplicate completion or a reversal is appended to `observedNonces`. A nonce already in the list is a no-op, so exact duplicates stay zero delta and reversal idempotency is preserved.
- Replay detection scans the union of `observedNonces` across the authoritative history, so a nonce first seen on a duplicate or a reversal is equally bound to that transaction and its later reuse for a different offer or transaction is `REJECT_NONCE_REPLAY`.
- The list is bounded by `MAX_OBSERVED_NONCES = 8`. Exceeding the bound fails closed as `REJECT_NONCE_HISTORY_EXHAUSTED` rather than dropping a nonce, which would reopen a replay hole.
- This is the smallest sound source-only model: no new persistence implementation is introduced. `observedNonces` is data on the existing append-only record.

## Timestamp ownership

- `firstObservedAt` and `lastObservedAt` are always the server `observedAt`. Provider clocks never set them.
- `providerOccurredAt` stores the provider's reported `occurredAt` separately, for evidence only, never for ordering.
- The maximum tolerated provider-clock skew is `MAX_PROVIDER_CLOCK_SKEW_MS = 24h`. Beyond it the callback is `REJECT_PROVIDER_CLOCK_SKEW`. An explicit `maxProviderClockSkewMs` may narrow the window but never widen it: an over-large bound fails closed as `REJECT_INVALID_EVENT`.
- Signature freshness uses two separate bounds: a maximum age (`DEFAULT_MAX_SIGNATURE_AGE_MS = 5m`) and a small maximum future skew (`DEFAULT_MAX_SIGNATURE_FUTURE_SKEW_MS = 30s`). A future timestamp beyond that skew fails as `FUTURE_TIMESTAMP`. Unknown algorithm or version already fail closed.

## Audit policy

`appendImmutableAuditEvent` is an explicit flag, set only for authenticated, meaningful state transitions and conflicts: crediting, reversal, nonce replay, and reopen-after-reversal. Every rejection, every idempotent duplicate, and all unauthenticated or forged input return `false`, so junk never reaches the append-only audit log. Reversal history is preserved: a reversal carries forward `providerOccurredAt`, `firstObservedAt`, `nonce`, amount, and currency.

## Claim and payout eligibility (source-only)

`assessPointsClaim` is a fail-closed, product-local gate. It performs no provider call, no payment, and no wallet transfer.

- It independently computes the available, non-reversed amount for a `(provider, offer, user, currency)` scope, optionally narrowed by explicit record keys.
- It rejects malformed identifiers, malformed currency, and claims that are zero, negative, non-finite, fractional, or out of range.
- It fails closed on malformed input records: any scoped or selected record with a non-safe, non-finite, zero, or negative reward amount, a malformed identifier/currency/state/timestamp, or an arithmetic sum that leaves the safe-integer range is `REJECT_INVALID_CLAIM`, never `ASSESS_CLAIMABLE`. `availableClaimableMinor` is a fail-closed read of the same scope and reports an available amount of `0` for such a scope rather than a partial or rounded total.
- It rejects overspend beyond the independently available amount.
- It rejects scopes containing a reversed record, unknown record keys, and currency mismatches.
- It rejects when claims are frozen.
- The default state is non-live: `payoutAllowed` is always `false` and `payoutBlockReason` names the blocking gate. When every caller-supplied readiness flag is `true`, the truthful reason is `SOURCE_ONLY_PAYOUT_DISABLED`: this module performs no payment at all, so it never claims an integrated payment rail is merely "missing" when the caller asserts one exists.

## Durable caller obligation (no persistence in this slice)

This module is pure source. The caller bears an explicit, load-bearing obligation for the guarantees above to hold in production:

- **Complete authoritative append-only history is required.** `applyVerifiedCompletion` and `assessPointsClaim` are only as good as the `records` array passed in. Replay detection, budget and per-user limits, and the claim's available amount all read that array. Passing a partial, filtered, paginated, or reconstructed history silently weakens every guarantee. The caller must pass the complete append-only ledger, including the full `observedNonces` history of every record.
- **One reward per completion depends on durable unique keys and a transaction.** The duplicate and replay checks here are pure functions over an in-memory array. They are not a uniqueness constraint. Exactly-once crediting depends on the caller enforcing unique `(providerId, offerId, providerTransactionId)` and unique `(providerId, nonce)` keys inside a database transaction, so that two concurrent callbacks cannot both observe an absent record and both credit. The caller must also durably persist each returned `next` record and honor `appendImmutableAuditEvent` for meaningful transitions and conflicts.
- Nothing in this slice persists state, so a restart that loses the ledger loses all replay, duplicate, and budget history.

## Safe projections

`toSafeLedgerRecordView`, `toSafeTransitionView`, and `toSafeClaimView` are allowlisted, field-by-field projections. They are the only sanctioned way to surface state, and they cannot carry a secret, a signature, a raw provider payload, or the internal nonce. Test-only secret injection is a verification input only and never enters an envelope or a projection.


## Prohibited in this slice

- click fraud, automatic tryouts, scripted provider actions, or fabricated completion;
- private endpoint scraping or collection of third-party user credentials;
- provider secrets, API keys, payment tokens, or Production database changes;
- live network calls, cash payouts, offer publication, deployment, or guaranteed-income claims.

## Release boundary

`TECHNICAL_FOUNDATION_READY` does not mean `LIVE_REWARDS_READY`. Live activation separately requires approved partners, signed offer terms, user eligibility and privacy review, funding, reconciliation, fraud controls, and owner authorization.

## Remaining gates

This slice is source-only and has no runtime dependencies beyond the Node.js standard library. Before any real points or payout exist, all of the following are still required and none are implemented here:

- **Durable storage:** the ledger, nonce history, and audit log exist only as in-memory values passed between calls. Nothing is persisted, so a restart loses all state and no replay history survives. See "Durable caller obligation" above: the caller must pass complete authoritative append-only history and enforce unique keys inside a transaction.
- **Approved provider integration:** no provider client, no key management, no real callback endpoint, and no reconciliation against a provider's own records.
- **Payment rail:** no payout instruction, no payment processor, no bank or wallet destination, and no settlement or refund path. `payoutAllowed` is hard-wired to `false`.
- **Transferable wallet:** points are not user-transferable, not withdrawable, and not cash-equivalent. There is no balance custody.
- **Operational controls:** no rate limiting, no alerting, no manual review queue, no dispute handling, and no fraud operations on top of the source-level rules.
- **Compliance and authorization:** offer publication, live reward balances, guaranteed-income claims, and owner sign-off all remain out of scope.
