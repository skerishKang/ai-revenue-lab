# Motion Spec — Task-to-Verified-Skill

## Purpose

Demonstrate the transformation of one bounded task into a human-reviewed reusable organizational skill without implying live execution.

## State contract

`idle|complete → running → complete`

Replay removes both `running` and `complete`, forces style recalculation, then applies `running`.

## Sequence

1. task boundary — 0ms;
2. guided steps — 100ms;
3. evidence attachment — 220ms;
4. reviewer correction — 340ms;
5. exception retention — 450ms;
6. skill version formation — 560ms;
7. final `VERIFIED ORGANIZATIONAL AI SKILL` seal — 700ms delay + 90ms duration.

Nominal final completion: 790ms.

## Completion authority

The actual final element is `#verified-skill-seal`. Its `skillSeal` `animationend` event is the normal completion authority. There is no `setTimeout` or `setInterval` fallback.

## Determinism

Replay 1 and Replay 2 must end with equivalent computed opacity and transform for the final seal. Motion uses fixed local CSS and no network or random values.

## Stability

All elements occupy final geometry before motion. Only opacity and transform change, so page geometry, scroll and replay-button focus remain stable.

## Reduced motion

`prefers-reduced-motion: reduce` applies the information-complete state immediately. Missing evidence and exception labels remain visible in all modes.
