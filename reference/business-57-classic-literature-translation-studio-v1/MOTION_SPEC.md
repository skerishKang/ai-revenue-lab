# Translation Weave Motion Specification

## Purpose

`Translation Weave / 번역 결 엮기` shows that a literary translation is built from traceable source choices rather than appearing as an unexplained model result.

## Duration

```text
Total intended signature duration: 680ms
```

Three source-to-rendering threads are staged with small delays. The final settled paragraph is already laid out before motion begins.

## Stable geometry contract

The following must remain stable before, during and after replay:

- review state surface;
- source fragment boxes;
- chosen-rendering boxes;
- final paragraph;
- review rail;
- replay control;
- focus position;
- scroll position.

No whole-state opacity or transform animation is allowed.

## Animated properties

Only these layers animate:

- SVG path `stroke-dashoffset` and opacity for `.thread`;
- inset emphasis on `.rendering` boxes.

The motion must not animate text position, container dimensions, page opacity or layout.

## Replay

The replay button:

1. removes `.is-replaying`;
2. forces style recalculation;
3. re-adds `.is-replaying`;
4. updates the live status text;
5. removes the replay class after the staged sequence completes.

Repeated playback must reach the same final frame.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- paths are fully drawn immediately;
- rendering emphasis is present immediately;
- no staged animation is required;
- the status text identifies the immediate completed state when replay is requested.

## Validation assertions

A browser validator should confirm:

- the weave state is visible before replay;
- source and final paragraph bounding boxes are unchanged;
- thread dash offsets change during normal replay;
- rendering boxes reach the same final emphasis on first and second replay;
- reduced-motion mode begins and remains in the complete final state;
- focus remains on the replay button after activation;
- scroll position remains stable.
