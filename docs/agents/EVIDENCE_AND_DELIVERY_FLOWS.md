# Evidence stages and delivery flows

A work contract selects the smallest evidence stage needed to answer the current product question, for example:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

Default MVP closeout flow:

```text
confirmed blocker
→ minimal fix
→ focused regression
→ relevant configured CI
→ authorized Production deployment
→ bounded real-account/primary-journey smoke
→ customer handoff
→ non-blocking hardening continues after handoff
```

## Default responsibility flow

```text
User request / portfolio authority
→ Web CTO exact work contract
→ Implementation Worker (local model) implementation
→ focused self-check + DEV_FAST_GATE
→ DEV_ACTOR_RELEASED; implementation may continue elsewhere
→ asynchronous Windows / Ubuntu / browser validators when required
→ FULL_VALIDATION on the final exact head
→ Web CTO final review
→ owner decision when materially required
→ merge
→ configured Production deployment and acceptance when authorized
```

This is a responsibility/evidence flow, not a mandatory product-stage sequence. A stage may be `NOT_REQUIRED` only with a recorded reason.
