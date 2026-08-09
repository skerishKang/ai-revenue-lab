# Agenda-to-Resolution / 안건에서 의결로

## State contract

`idle|complete → running → complete`.

Replay removes `complete` and `running`, forces style recalculation, then applies `running`. In reduced motion, replay immediately applies `complete`.

## Sequence and target

1. notice and agenda align — 0–190ms
2. rule basis appears — 110–300ms
3. public/private ribbons separate — 200–390ms
4. budget/vendor sheets enter — 290–500ms
5. dissent remains visible — present before, during and after motion
6. quorum/result aligns — 410–600ms
7. human-reviewed resolution seal — 520–700ms
8. resident public notice — 610–760ms

The final `.public-notice-complete` animation is the normal completion authority. No fixed timeout declares completion.

## Stability

The motion stage has fixed grid tracks and minimum height. Only opacity, transform and clip-path animate. Dissent, rule basis, budget ceiling and disclosure labels remain present at completion.

## Reduced motion

`@media (prefers-reduced-motion: reduce)` disables animation and exposes all final elements immediately.
