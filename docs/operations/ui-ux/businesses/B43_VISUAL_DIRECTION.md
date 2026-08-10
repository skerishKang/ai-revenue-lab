# B43 — AI Software Factory Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://43-ai-software-factory.pages.dev/`. Current light cards do not express production/verification flow and duplicate the systems family template.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A software request becomes a bounded work contract, passes through small production/change packets and verification gates, then reaches human review.

```text
REQUEST → WORK CONTRACT → PRODUCTION PACKETS → VERIFICATION → HUMAN REVIEW
```

Core object: **the work contract moving through an assembly/verification line**.

## Reserved territory — Work Contract Assembly Line

- request decomposed into bounded work packets
- contract scope/constraints visible at every stage
- build/change packets move through a clear line
- verification gate attached to exact packet
- human acceptance at the end
- blueprint/industrial notation used functionally

Avoid cartoon factory, dark control-tower clone, kanban board and generic cards.

## Differentiation

B42 = portfolio-wide development operations overview. B43 = one bounded software request moving through production. B32 = reusable organizational skill creation.

## Acceptance criteria

1. request→contract→packet→verification progression visible spatially;
2. scope/constraints remain persistent;
3. verification attaches to exact output;
4. human review remains final;
5. generic systems template is gone;
6. Mobile becomes a sequential contract/packet view;
7. current software-work contracts remain intact.
