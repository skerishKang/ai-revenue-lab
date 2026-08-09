# Signature motion — Chapter Pulse

Duration: **680ms** (required range: 640–720ms)

## Sequence

1. Active chapter rule advances from 48% to 78%.
2. Restrained waveform ribbon reveals through opacity and vertical scale.
3. Chapter title and transcript excerpt settle into the next deterministic synthetic passage.
4. Source citation appears last.
5. Layout dimensions, keyboard focus and scroll position remain fixed.

## Trigger

The `챕터 펄스 보기` review button invokes `window.__PAC_REVIEW__.runPulse()`.

This is visual-state inspection only. It does not play audio or establish accepted UX.

## Reduced motion

Under `prefers-reduced-motion: reduce`, all transitions complete effectively immediately and the final chapter, waveform and citation state remain visible.

## Prohibited motion intentionally excluded

- bouncing equalizer;
- spinning record;
- particles;
- voice avatar animation;
- 3D audio object;
- scroll-coupled or focus-moving transition.
