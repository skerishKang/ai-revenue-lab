# Motion Specification

## Signature

```text
Request-to-Private-Data-Access-Spec
```

## Meaning

The motion does not represent a live connector. It visually converts a synthetic request into a review-ready access specification:

```text
authorized purpose
→ requester and data owner
→ requested scope
→ least-privilege approved scope
→ field mapping and exclusions
→ credential / retention / audit controls
→ revocation and residual conditions
→ HUMAN-APPROVED PRIVATE DATA CONNECTOR ACCESS SPEC
```

## Timing contract

- Eight nodes use opacity and transform only.
- Each node animation duration: `240ms`.
- Stagger delays: `0, 70, 140, 210, 280, 350, 420, 510ms`.
- The final node is the actual last animation and ends at nominal `750ms`.
- Normal completion authority is the final node's actual `animationend` event for `motion-reveal`.
- There is no completion timeout or fixed JavaScript delay.
- On completion the board removes `is-running`, applies `is-complete`, and therefore has `animation: none`.
- Elapsed wall-clock time is recorded in `data-motion-elapsed-ms` for validation.

## Replay contract

Replay:

1. preserves active focus and window scroll position;
2. removes running and complete classes;
3. forces a synchronous style reset with `offsetWidth`;
4. starts a new deterministic animation run;
5. finalizes only from the final element's `animationend`;
6. restores focus/scroll if needed;
7. leaves identical final computed styles and geometry across runs.

## Reduced motion

When `prefers-reduced-motion: reduce` is active:

- all eight nodes are immediately information-complete;
- no animation is started;
- elapsed motion time is recorded as `0`;
- no content or boundary is omitted.

## Persistent completion boundaries

The following remain visible after completion and replay:

```text
PROHIBITED PATH
SENSITIVE FIELD — EXCLUDED
NO SECRET DISPLAY
RETENTION LIMIT
ACCESS REVOCABLE
AUDIT EVIDENCE — NOT EMPLOYEE MONITORING
CONNECTOR READINESS — NOT CONNECTED
```
