# Motion Specification · Signal Convergence / 신호 합류

## Purpose

Show that several source signals can support one dossier while contradictory evidence remains visibly unresolved and human review appears last.

## Duration

- Nominal total: `680ms`
- Contract range: `640–720ms`

## Sequence

| Time | Event |
|---:|---|
| 0–120ms | Source markers and evidence strips activate through opacity and a 4px local transform. |
| 120–470ms | Corroborating evidence strips translate toward the selected dossier edge. The atlas and layout do not move. |
| 240–520ms | A source-chain line reveals with `clip-path`. |
| 180–560ms | Conflicting evidence remains offset and receives a restrained contradiction rule; it never merges or disappears. |
| 520–680ms | Human-review seal fades and scales from 0.96 to 1.00. |

## Implementation constraints

- Allowed: `transform`, `opacity`, `clip-path`.
- Map, page frame, focus, and scroll position remain stable.
- No globe spin, particles, route-flight animation, bounce, 3D, viewport motion, or node-graph spectacle.
- Motion replay is a visual-review control only.

## Reduced motion

Under `prefers-reduced-motion: reduce`, the complete final evidence state is rendered immediately. No travel transform or delayed human-review seal is used.
