# Signature motion specification

## Name

```text
Source-to-Format Relay / 원본 맥락 릴레이
```

## Purpose

Demonstrate that one fixed source fragment passes through a master-story decision into genuinely different medium treatments while omissions, rewrites and final human review remain visible.

## Nominal timing

```text
720ms visual sequence
800ms completion marker
```

| Stage | Nominal start | Element | Treatment |
|---|---:|---|---|
| 1 | 0ms | selected source fragment | remains fixed; no geometry change |
| 2 | 80ms | master-story annotation | opacity + 8px vertical transform + clip reveal |
| 3 | 180ms | editorial rule | horizontal scale from fixed origin |
| 4 | 280ms | article proof | opacity + transform + clip reveal |
| 5 | 380ms | audio adaptation | opacity + transform + clip reveal |
| 6 | 460ms | video adaptation | opacity + transform + clip reveal |
| 7 | 540ms | visual-card adaptation | opacity + transform + clip reveal |
| 8 | 640ms | human-review mark | opacity + restrained scale; ends by approximately 780ms |

## Stability contract

- the selected source remains in place;
- no container height, width or grid track changes during replay;
- no typewriter, page flip, particle, floating paper, parallax, node graph or AI glow;
- the replay button remains focused after activation;
- `window.scrollX` and `window.scrollY` are restored on the next animation frame and at completion;
- URL state and page geometry do not change;
- final omission/rewrite notes remain visible.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- animation durations and delays collapse to effectively zero;
- all relay elements render in the same final visible state;
- the human-review mark remains present;
- focus and scroll preservation behavior is unchanged.

## Implementation hooks

- container: `[data-relay]`
- running class: `.relay-running`
- completion marker: `data-motion-state="complete"`
- replay control: `[data-action="replay"]`
