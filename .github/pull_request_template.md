## Product evidence goal

- Business:
- Target customer/user:
- Evidence goal: `VISUAL_DESIRABILITY / INVESTOR_STORY / USER_JOURNEY / TECHNICAL_FEASIBILITY / CUSTOMER_PILOT / REVENUE_TEST`
- Product stage: `COMPETITIVE_DEMO / INVESTOR_DEMO / MVP_VERTICAL_SLICE / SERVICE_LED_PILOT / RUNTIME_PILOT / COMMERCIAL_HARDENING`
- Primary product promise:

## Scope

- In scope:
- Out of scope:
- Live behavior:
- Simulated or service-led behavior:

## Competitive references

- Direct/adjacent products:
- Visual/interaction references:
- Screen-level patterns adopted:
- Patterns rejected:
- How this result improves on the benchmark:
- `REFERENCE_BOARD.md` or equivalent:

## Changes

List the exact files or modules changed and why.

## Product and visual evidence

- Primary journey or demo sequence:
- Desktop captures:
- Mobile captures:
- Motion/video evidence:
- Before/after evidence when upgrading:
- Image/media source documentation:
- Content realism and fixture inventory:

## Technical evidence

- Tests run:
- Test results and exit codes:
- Lint/type-check results:
- Browser/runtime results:
- Console/page/network failures:
- Exact head and changed scope:

## Backend and operations

- Backend mode: `NO_BACKEND / DETERMINISTIC_SIMULATION / SERVICE_LED / LOCAL_RUNTIME / LIVE_VERTICAL_SLICE / PILOT_RUNTIME / COMMERCIAL_HARDENING`
- Data and persistence boundary:
- Authentication/authorization:
- AI provider and fallback:
- Observability:
- Cost estimate or ceiling:
- Recovery path:

## Independent verdicts

- `TECHNICAL_UI_PASS`:
- `VISUAL_QUALITY_PASS`:
- `MARKET_REFERENCE_PASS`:
- `INVESTOR_DEMO_PASS`:
- MVP or pilot verdict:
- Owner decision required:

## AI production record

- Implementation model/provider:
- Free calls or quota used:
- Paid-model use and reason:
- Human review time:

## Material risks and limitations

List concrete risks, evidence, mitigation, and residual risk. Do not use generic warnings as a substitute for product decisions.

## Completion checklist

- [ ] The product promise is demonstrated, not merely described.
- [ ] Reference influence is visible in the result and documented at screen level.
- [ ] The result has been compared side by side with selected benchmarks.
- [ ] Images, content, typography, composition, motion, and mobile behavior received independent review.
- [ ] Live, simulated, and service-led behavior are distinguished truthfully.
- [ ] Acceptance criteria are demonstrated.
- [ ] No secrets, tokens, credentials, or unauthorized private data were committed.
- [ ] Model/provider configuration remains replaceable where applicable.
- [ ] Documentation was updated when behavior or decisions changed.
- [ ] Exact changed files and validation evidence are included.
- [ ] Last known-good Production source/configuration and reviewed fix-or-revert recovery are recorded when applicable.

### Deployment when applicable

- [ ] Git-connected project: the approved merge is the normal deployment action; no unauthorized second deployment was created.
- [ ] Automatic Production deployment ID/status and resulting source are recorded.
- [ ] Real-environment product acceptance covers the primary journey, not only root HTTP status.
- [ ] Preview, staging, or manual-deployment exception: none, or an explicit owner decision is linked.