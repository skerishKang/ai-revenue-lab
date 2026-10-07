# Provider onboarding status

```text
AGNES_AI = CODE_INTEGRATION_CANDIDATE
AGNES_MODEL = agnes-2.5-flash                       (historical #917 intake line)
AGNES_CURRENT_REGISTERED_MODEL = agnes-ai/agnes-3.0-flash   (#2133 manual-pin; #3554 Plus TEXT role)
OWNER_LOCAL_SMOKE = ALLOWED_AFTER_CODE_ACCEPTANCE
PUBLIC_SHARED_FREE_POOL = HOLD_PENDING_TERMS_CONFIRMATION
GMI_MINIMAX_PROMOTION = NOT_ONBOARDED
```

`AGNES_MODEL` above is the original 2026-08-27 intake value and is kept only as
history. The model that B14 actually registers today is
`agnes-ai/agnes-3.0-flash` (`app/pilot/agnes_provider.py`), and owner decision
2026-10-07 (#3554) selected it for the Padiem Plus **text** role. The vision
role is still unselected, so `image` remains unavailable for Plus.

The `PUBLIC_SHARED_FREE_POOL` gate stays open on the terms evidence itself.
#3554 records the owner's decision to accept the known risk for this lane
(`DATA_HANDLING_REVIEW=RISK_ACCEPTED_BY_OWNER`,
`COST_STATUS=UNCONFIRMED_ACCEPTED_BY_OWNER`); accepting a risk is not the same
as the terms confirming shared-key or commercial free-tier use, so the gate is
left visible rather than silently cleared.
