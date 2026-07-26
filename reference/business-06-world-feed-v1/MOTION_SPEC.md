# Horizon Shift Motion Specification

## Purpose

`Horizon Shift` communicates that the user’s viewing horizon has moved from one place or topic layer to another while preserving source context.

It is a Phase 1 visual demonstration, not accepted navigation or personalization UX.

## Sequence

Target total: **650ms** within the allowed **550–750ms** range.

1. **0–650ms — dominant image**
   - current image moves left and fades;
   - next image enters from the right;
   - CSS `transform: translateX()` and `opacity` only.
2. **90–580ms — place/topic label**
   - current label and headline move slightly left and fade;
   - next label and headline trail from the right;
   - approximately 90ms behind the image start.
3. **120–660ms — compact posts**
   - three posts recompose vertically;
   - 60ms stagger between items;
   - `translateY()` and `opacity` only.
4. **stable throughout — source line**
   - source/provenance line does not leave the composition;
   - it preserves orientation while the topic image and posts move.

## Implementation

- CSS animations and transforms.
- Minimal JavaScript only to add/remove the deterministic `is-shifting` class.
- No WebGL, canvas animation, 3D globe, particles, animation framework, or external dependency.
- The topic state uses the same motion grammar for the `장소와 동네` / `공예와 손` visual switch.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- transition and animation durations collapse to an effectively immediate change;
- the incoming image and label become visible without travel choreography;
- the source line remains unchanged;
- the review button text reports `즉시 전환됨`.

The document root exposes `data-reduced-motion="true|false"` for deterministic browser evidence.

## Review controls

- `Horizon Shift` state button opens the motion surface.
- `모션 재생` starts one deterministic sequence.
- The button remains keyboard operable and exposes `aria-busy="true"` during the preview.
