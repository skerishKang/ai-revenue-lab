# Motion Specification — Route Trace

## Purpose

Make automatic model selection understandable. Motion represents route eligibility and final selection; it is not decorative loading noise.

## Sequence

1. The request capsule gains focus.
2. A thin active line extends toward the candidate rail.
3. Eligible route nodes become legible in order.
4. Excluded nodes dim and expose a short reason.
5. The selected line reaches the final model/Provider node.
6. The result panel reveals the selected route and evidence label.

## Timing

```text
request emphasis: 120 ms
candidate reveal: 180 ms staggered
selected path: 320 ms
result reveal: 180 ms
```

Total visible transition should remain below approximately 900 ms.

## Spatial rules

- the active path always moves from intent to route to result;
- no random particles or looping glow;
- route geometry remains stable between states;
- content does not shift when evidence appears;
- mobile uses a vertical path instead of squeezing the desktop horizontal path.

## Reduced motion

With `prefers-reduced-motion: reduce`:

- all states appear immediately;
- no path drawing, translation or stagger;
- selected and excluded states remain fully distinguishable through text, weight and border style.

## Keyboard behavior

Changing purpose or route preference through keyboard controls triggers the same deterministic final state. Focus remains on the changed control; motion never steals focus.

## Replay

The `경로 다시 보기` review control may replay the sequence. Repeated playback must produce identical geometry and final evidence.