# Motion specification — Brief-to-Content-Production-Kit

## Purpose

Show one authorized synthetic source brief becoming a human-approved reusable production kit while rights, verification, unsupported-claim, style-imitation and publication limits remain visible.

## Sequence

```text
rights-verified brief
→ content structure
→ format transformations
→ draft variants
→ human-reviewed variant
→ quality exceptions
→ reusable production recipe
→ HUMAN-APPROVED CONTENT PRODUCTION KIT
```

## Completion authority

- Replay removes `is-running` and `is-complete`, forces layout, then adds `is-running`.
- The final element is `.final-element.kit-seal`.
- Completion is authorized only by its actual `animationend` event where `animationName === "kitComplete"`.
- No completion timeout, interval or delayed callback exists.
- Nominal completion duration: `760ms`.
- `completeMotion()` converts the board to the single stable `is-complete` end state.

## Determinism

Replay 1 and Replay 2 must produce equal final computed style, final geometry and screenshot bytes at the tested viewport. All animated properties return to the same explicit complete values. No random number, time-based source, network data or persisted state is used.

## Stability

The replay control captures `document.activeElement`, `scrollX` and `scrollY`; the next animation frame restores scroll and focus with `preventScroll`. The motion uses opacity and transforms only, so layout geometry is stable.

## Reduced motion

When `prefers-reduced-motion: reduce` matches, replay calls `completeMotion()` immediately. CSS also collapses animation duration and forces every node and the final mark to an information-complete state.

## Retained authority after completion

- `SOURCE RIGHTS VERIFIED — SYNTHETIC`
- `FACT CHECK NOT PERFORMED`
- `UNSUPPORTED CLAIM — HOLD`
- `STYLE IMITATION PROHIBITED`
- `NOT PUBLISHED`
