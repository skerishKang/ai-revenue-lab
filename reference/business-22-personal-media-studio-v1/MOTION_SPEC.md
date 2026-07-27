# Signature motion specification

## Name

```text
Source-to-Format Relay / 원본 맥락 릴레이
```

## Purpose

Keep one source fragment fixed while its master-story annotation and medium-specific article, audio, video and visual-card adaptations appear in sequence. Omission and rewrite notes remain visible, and the human-review mark resolves last.

## Timing contract

```text
computed final visual end: 740ms
allowed range: 680–760ms
completion mechanism: final .step-review animationend
```

| Stage | Start | Duration | End | Element |
|---|---:|---:|---:|---|
| source | 0ms | fixed | — | selected source fragment |
| annotation | 80ms | 120ms | 200ms | master-story annotation |
| rule | 180ms | 120ms | 300ms | editorial rule |
| article | 280ms | 120ms | 400ms | article proof |
| audio | 380ms | 120ms | 500ms | audio adaptation |
| video | 460ms | 120ms | 580ms | video adaptation |
| visual card | 540ms | 120ms | 660ms | visual-card adaptation |
| human review | 620ms | 120ms | **740ms** | final review mark |

The UI label, CSS computed timing, JavaScript completion state and machine-readable evidence all use this 740ms contract.

## State contract

```text
idle or complete
→ running
→ complete
```

`runRelay()` explicitly sets `data-motion-state="running"` before restarting the CSS animation. The previous completion listener is removed. The final `.step-review` `relayReview` animation emits `animationend`, which sets `data-motion-state="complete"`.

No fixed completion `setTimeout` or duplicated JavaScript duration constant is used.

## Stability contract

- the selected source remains in place;
- focus remains on the replay control;
- scroll position remains unchanged;
- document height and source geometry remain unchanged;
- medium-specific omission and rewrite notes remain visible;
- the human-review mark is visible in the final state.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- every relay element is immediately visible;
- the human-review mark is visible;
- state becomes `complete` immediately;
- replay focus, scroll and geometry remain unchanged.

## Implementation hooks

- container: `[data-relay]`
- running class: `.relay-running`
- start state: `data-motion-state="running"`
- final animation: `.step-review` / `relayReview`
- final state: `data-motion-state="complete"`
- replay control: `[data-action="replay"]`
