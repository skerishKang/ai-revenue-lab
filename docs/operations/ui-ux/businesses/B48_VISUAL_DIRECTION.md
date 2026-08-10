# B48 — AI Verification Engine Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh platform audit: run `31422928265`, artifact `9076118820`, canonical `https://48-ai-verification-engine.pages.dev/`. Current generic light cards do not distinguish reusable verification infrastructure from B15/B33.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A claim passes through explicit evidence checks, limitations and verification status before a human makes the final decision.

```text
CLAIM → EVIDENCE CHAIN → VERIFICATION GATE → HUMAN DECISION
```

Core object: **the claim-evidence chain and verification gate**.

## Reserved territory — Claim-Evidence Gate

- claim as a bounded unit
- evidence nodes/slips connected by support/contradict/unknown relation
- verification criteria/gate visible
- limitations remain beside status
- human decision stamp/record final

Avoid newsroom styling, research notebook styling, confidence-meter spectacle and generic cards.

## Differentiation

B15 = editorial newsroom producing briefing. B33 = durable personal research memory. B48 = reusable verification engine/gate.

## Acceptance criteria

1. evidence chain is visible and inspectable;
2. support/contradict/unknown relations are explicit;
3. limitations survive the verification status;
4. human decision remains final;
5. generic B45–B49 shell is gone;
6. Mobile preserves claim→evidence→gate→decision order;
7. current verification boundaries remain intact.
