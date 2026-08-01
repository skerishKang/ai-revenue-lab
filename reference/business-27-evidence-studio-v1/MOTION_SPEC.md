# Motion Spec · Chronology Lock / 시간축 고정

Target CSS contract: approximately 680ms; final timing must be measured by the Local Validator from computed style.

Sequence:
1. source markers appear;
2. uncertain interval narrows;
3. corrected event aligns;
4. human-review seal appears last.

Implementation contract:
- `.chronology-lock` maintains fixed geometry.
- replay selector: `[data-motion-replay]`.
- motion host: `[data-chronology-lock]`.
- runtime states: `idle|complete → running → complete`.
- completion source: `animationend` from `.review-seal`, not a fixed timer.
- conflicting evidence remains visible throughout.
- `prefers-reduced-motion: reduce` immediately exposes the complete final mapping.
- timeline, source panel, focus and scroll must remain stable; Local Validator owns final proof.
