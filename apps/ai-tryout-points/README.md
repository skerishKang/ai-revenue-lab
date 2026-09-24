# B65 AI Tryout Points

B65 is a distinct side-income product for rewards earned after a provider-verified AI product tryout or quality-check action is completed.

## Product boundary

- **B64 AI Reward Router:** rewarded ad, click, visit, and later earning-route discovery.
- **B65 AI Tryout Points:** points earned only after a provider-signed action-completion event.
- A click or page visit is never a B65 completion authority.
- Provider secrets, keys, payout execution, Production deployment, and live reward balances are outside this foundation slice.

## Current implementation

- typed tryout offer and immutable reward value contracts;
- HMAC-SHA256 completion callback verification with constant-time comparison and timestamp freshness;
- completion, duplicate, reversal, identity/value mismatch, stale, and budget fail-closed rules;
- a product-local points ledger contract;
- Node.js built-in test suite with no runtime dependency.

The current state is technical foundation only. It does not expose real offers or claim real income.
