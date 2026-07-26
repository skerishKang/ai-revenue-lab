# Cover Reveal Motion Specification

## Purpose

`Cover Reveal` turns the finite issue cover into the opening feature spread while preserving issue identity. It is a Phase 1 visual demonstration, not accepted navigation or a completed reading flow.

## Timing

Target total duration: **680ms**, within the required **550–750ms** range.

1. **0–680ms — portrait crop expansion**
   - the cover portrait expands from its cover crop into the spread image field;
   - CSS `transform`, `clip-path`, and `opacity` only.
2. **80–620ms — masthead relocation**
   - the masthead reduces and moves to the persistent issue rail;
   - issue number remains visible throughout.
3. **120–680ms — coverline transformation**
   - three coverlines fade and shift into a compact contents index;
   - the feature headline and opening copy enter with a restrained vertical offset.
4. **stable context**
   - issue number, date, fictional subject name, and page context remain visible.

## Implementation

- one deterministic class toggle: `.is-revealed`;
- CSS transitions only;
- no 3D rotation, canvas, WebGL, animation framework, particles, or network dependency;
- replay button is keyboard operable and exposes `aria-pressed` and status text;
- `Escape` returns the reveal surface to the cover state.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- all travel and clip transitions are disabled;
- the final spread appears immediately;
- opacity does not animate;
- issue identity remains present;
- document root exposes `data-reduced-motion="true"` for deterministic evidence.
