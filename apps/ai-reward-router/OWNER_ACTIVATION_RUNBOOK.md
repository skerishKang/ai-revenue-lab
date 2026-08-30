# B64 Owner Activation Runbook — Deferred Provider Accounts

This runbook is intentionally separate from CENTRAL implementation. It is used only after the owner chooses to create/approve provider accounts.

## Current default

All provider integrations remain disabled:

- `B64_AYET_MODE=DISABLED`
- `B64_ADSCEND_MODE=DISABLED`
- `B64_TREMENDOUS_MODE=DISABLED`

The product must boot normally in this state and expose zero real reward cards when no live-authorized supply exists.

Never commit real provider IDs, API keys, access tokens, funding credentials, recipient data, or account screenshots containing secrets.

## 1. ayeT owner action — issue #1116

When the owner is ready:

1. Create/approve the publisher account and B64 website placement.
2. Create the Rewarded Video ad slot.
3. Complete provider-required ads.txt / consent / demand setup.
4. Put the resulting values only in the production secret/config environment:
   - `B64_AYET_PUBLISHER_ID`
   - `B64_AYET_PLACEMENT_ID`
   - `B64_AYET_REWARDED_ADSLOT_ID`
   - `B64_AYET_PUBLISHER_API_KEY` — server-side secret only
5. Set `B64_AYET_MODE=CONFIGURED` while validating server initialization.
6. Observe real South Korea fill and signed callback/S2S behavior.
7. Only after owner acceptance set:
   - `B64_AYET_OWNER_AUTHORIZED=true`
   - `B64_AYET_MODE=LIVE_AUTHORIZED`

Do not use `LIVE_AUTHORIZED` merely because the fields are populated.

## 2. Adscend owner action — issue #1117

When the owner is ready:

1. Create/approve the publisher account for the B64 GPT/cash or external-value reward use case.
2. Create the website Offer Wall / video profile.
3. Configure stable opaque user IDs and provider-supported server postback verification.
4. Put values only in production config/secrets:
   - `B64_ADSCEND_PUBLISHER_ID`
   - `B64_ADSCEND_OFFERWALL_PROFILE_ID`
   - `B64_ADSCEND_API_KEY` — server-side secret only
5. Set `B64_ADSCEND_MODE=CONFIGURED` during validation.
6. Verify South Korea video inventory and enforce the existing offer-level cash-incentive policy gate.
7. Only after owner acceptance set:
   - `B64_ADSCEND_OWNER_AUTHORIZED=true`
   - `B64_ADSCEND_MODE=LIVE_AUTHORIZED`

Provider account approval alone does not authorize every offer. Offer-level policy remains fail-closed.

## 3. Tremendous owner action — issue #1118

When the owner is ready:

1. Create/approve the production organization and API access.
2. Configure a supported funding source.
3. Fetch the live South Korea reward catalog and verify the intended payout product(s).
4. Put values only in production config/secrets:
   - `B64_TREMENDOUS_CAMPAIGN_ID`
   - `B64_TREMENDOUS_ACCESS_TOKEN` — server-side secret only
5. Set `B64_TREMENDOUS_MODE=CONFIGURED` during validation.
6. Verify live SKU denomination/currency limits, risk-hold policy, idempotency and delivery reconciliation.
7. Perform an authorized low-value test reward only when operational policy permits.
8. Only after owner acceptance set:
   - `B64_TREMENDOUS_OWNER_AUTHORIZED=true`
   - `B64_TREMENDOUS_MODE=LIVE_AUTHORIZED`

No external reward order may originate from a provisional or reversed ad event.

## 4. Activation invariant

`LIVE_AUTHORIZED` means all of the following are true:

- owner explicitly approved activation;
- required non-secret identifiers exist;
- required server secrets exist in the deployment secret store;
- provider policy/use-case authority has been established;
- real supply or payout behavior has been observed where required;
- fraud/duplicate/reversal controls are active;
- consumer exposure still passes the AD_CLICK fail-closed card contract.

If any condition becomes unknown, disable the provider rather than guessing.
