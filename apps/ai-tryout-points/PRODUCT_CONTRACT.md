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
3. the signed timestamp is inside the accepted freshness window;
4. the event identifies an approved action-completion type, never click or visit;
5. provider, offer, user, amount, and currency match the current local transaction;
6. the provider transaction is new and not previously reversed;
7. per-user and funded-budget limits remain available.

Client state, localStorage, a page redirect, a button click, or a browser-generated completion claim is never settlement authority.

## Ledger rules

- A completion creates exactly one positive ledger entry.
- A replay or duplicate creates no balance mutation.
- A reversal creates one negative entry and preserves the original completion.
- A reversed transaction cannot silently reopen.
- Amounts are integer minor units; floating-point money is forbidden.
- Provider-reported reward value may be confirmed by signed evidence but cannot silently change an offer.
- This slice creates points accounting evidence only. It does not create a transferable wallet, cash custody, or external payout order.

## Prohibited in this slice

- click fraud, automatic tryouts, scripted provider actions, or fabricated completion;
- private endpoint scraping or collection of third-party user credentials;
- provider secrets, API keys, payment tokens, or Production database changes;
- live network calls, cash payouts, offer publication, deployment, or guaranteed-income claims.

## Release boundary

`TECHNICAL_FOUNDATION_READY` does not mean `LIVE_REWARDS_READY`. Live activation separately requires approved partners, signed offer terms, user eligibility and privacy review, funding, reconciliation, fraud controls, and owner authorization.
