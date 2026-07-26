# Cover Reveal Motion Specification

## Purpose

`Cover Reveal` turns the finite issue cover into the opening feature spread while preserving issue identity. It is a Phase 1 visual demonstration, not accepted navigation or a completed reading flow.

## Layer contract

- `.reveal-feature` is fully rendered from the first frame at `opacity: 1` and `z-index: 1`.
- `.reveal-cover` remains above it at `z-index: 2` and completely covers the spread in the initial state.
- The feature layer never rises above the cover and never waits for an opacity delay.
- The stage background is therefore never exposed as an intermediate frame.
- Controls remain above both layers at `z-index: 8`.

## Timing

Target total duration: **680ms**, within the required **550–750ms** range.

1. **0–680ms — cover mask removal**
   - the cover moves from `clip-path: inset(0)` to `inset(0 0 0 100%)`;
   - the left edge opens first, revealing the persistent feature page rail before the cover masthead leaves;
   - CSS `clip-path` and the existing portrait `transform` are the only travelling properties.
2. **stable underlay — complete feature spread**
   - the feature image, headline, deck, quote, masthead, issue number, and page rail are opaque before the mask starts;
   - no base-paper gap or translucent text frame is permitted.
3. **stable controls and orientation**
   - the masthead and issue context are supplied by the cover at the start and by the feature rail as it is exposed;
   - the reveal control and status remain visible throughout.
4. **reverse transition**
   - `표지로 돌아가기` removes `.is-revealed`;
   - the same 680ms clip transition covers the pre-rendered feature without a blank frame;
   - `Escape` uses the same final cover state.

## Replay contract

- first reveal, button return, and second reveal use the same class state and timing;
- the control remains keyboard operable and updates `aria-pressed`;
- status text distinguishes transition, completed spread, return, and completed cover states.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- all cover and portrait transitions are disabled;
- the pre-rendered spread appears immediately when `.is-revealed` is applied;
- return is also immediate;
- issue identity and controls remain present;
- the document root exposes `data-reduced-motion="true"` for deterministic evidence.
