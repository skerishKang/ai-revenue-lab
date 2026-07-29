# Motion specification

## Signature

`Task-to-Human-Approved-Routing-Policy / 작업 분류에서 사람 승인 모델 라우팅 정책으로`

## Sequence

1. task requirement;
2. privacy and quality hard constraints;
3. weighted preferences;
4. fictional candidate inventory;
5. evidence and availability;
6. candidate exclusion;
7. primary and fallback policy;
8. no-safe-route and human handoff;
9. `HUMAN-APPROVED MODEL ROUTING POLICY`.

## Completion authority

The final `.routing-policy-record` runs animation `routingPolicyComplete`. Its actual `animationend` event is the only normal-motion completion authority. JavaScript contains no fixed completion timeout.

Computed nominal completion:

- delay: 650ms;
- duration: 110ms;
- total: 760ms.

## Replay invariants

- deterministic class reset and forced style recalculation;
- Replay 1 and Replay 2 final computed styles, screenshot hashes and geometry equal;
- replay-button focus stable;
- scroll position stable;
- route-board geometry stable;
- reduced motion immediately reaches information-complete state.

## Persistent boundary register

The final decision and dedicated mobile brief retain:

- `HARD CONSTRAINT`;
- `CANDIDATE EXCLUDED`;
- `AVAILABILITY — UNKNOWN / UNAVAILABLE`;
- `PRIMARY ROUTE — NOT EXECUTED`;
- `FALLBACK ROUTE — NOT EXECUTED`;
- `NO SAFE ROUTE`;
- `HUMAN HANDOFF`;
- `BEST MODEL NOT CLAIMED`;
- `MODEL/PROVIDER NOT ACTIVATED`.

These are outside the animated trace and remain visible after normal and reduced-motion completion.
