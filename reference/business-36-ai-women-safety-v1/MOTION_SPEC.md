# Motion specification

## Signature motion

`Situation-to-Safety-Response-Brief` / `상황 기록에서 사람 검토 안전대응 브리프로`

## Sequence

1. user account
2. observable context
3. uncertain concern
4. bounded options
5. trusted-contact plan
6. accessibility and evidence boundaries
7. escalation handoff
8. unresolved uncertainty retention
9. `HUMAN-REVIEWED SAFETY RESPONSE BRIEF`

## Authority and timing

- Replay is deterministic and restarts only by removing/reapplying CSS classes after a forced style flush.
- The final `.final-seal` animation is named `briefComplete`.
- Its real `animationend` event is the sole normal-motion completion authority.
- No fixed completion timeout is used.
- Nominal final-element duration: **760ms**.
- The complete state is a stable class state; Replay 1 and Replay 2 must produce equal final computed styles and geometry.
- Focus and scroll are captured before replay and restored with `preventScroll` on the next animation frame.

## Persistent information after completion

- `MISSING EVIDENCE`
- `UNRESOLVED UNCERTAINTY`
- `NOT A GUARANTEE OF SAFETY`
- `EMERGENCY RESPONSE OUT OF SCOPE`
- `NO CRIME OR PERSON-RISK INFERENCE`

## Reduced motion

When `prefers-reduced-motion: reduce` matches, replay immediately enters the information-complete state. No content, authority label or retained boundary is removed.
