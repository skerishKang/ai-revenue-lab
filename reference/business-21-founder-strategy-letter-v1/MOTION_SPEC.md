# Signature Motion — Argument Thread / 논점 연결

Target duration: **680ms**.

## Sequence

1. Evidence markers 01–03 activate at 80–180ms.
2. Evidence rules extend toward the central strategic tension at 180–330ms.
3. The dissenting evidence remains offset and visible at 330ms.
4. The current recommended posture appears at 430ms.
5. The founder review mark appears last at 560ms.
6. Layout, focus and scroll position remain fixed for the entire sequence.

## Implementation constraints

- CSS opacity, transform and clip-path only;
- no node graph, particle, animated chart, typewriter or glow;
- no viewport movement;
- replay control remains keyboard accessible;
- animation never changes focus.

## Reduced motion

Under `prefers-reduced-motion: reduce`, all evidence markers, rules, dissent, posture and founder mark render immediately in the same final positions.
