# Counter-to-Page Motion Specification

## Purpose

`Counter-to-Page / 카운터에서 지면으로` assembles the physical evidence of one shop into a finished issue cover.

## Intended duration

Approximately `680ms`.

1. Receipt, label and photo fragments align.
2. Product image settles into its crop.
3. Headline rule and issue number appear.
4. Owner quotation appears last.

The final owner quotation animation is `revealQuote`, ending nominally at `500ms + 180ms = 680ms`. Its `animationend` event is the completion authority in `scripts/review.js`.

## Stable geometry

The issue sheet, hero crop, headline, folio, replay button, scroll position and focus must remain stable. Only fragment transforms/opacity, hero clip-path/scale, headline rule, issue number and quotation emphasis animate.

## Replay

Control: `#replay-counter`.

Replay removes and re-adds `.is-replaying`, forces style recalculation, and completes only when `revealQuote` fires `animationend`. Repeated playback is deterministic and the replay control is not replaced or moved.

## Reduced motion

`@media (prefers-reduced-motion: reduce)` exposes the completed composition immediately. JavaScript does not add the replay class in reduced-motion mode and updates the live status text.

## Local Validator contract

Measure computed timing, layout geometry, focus, scroll, replay equivalence and reduced-motion information equivalence independently. Web implementation does not claim those validation results.
