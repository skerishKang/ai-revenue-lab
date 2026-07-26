# Motion specification — Format Relay / 포맷 릴레이

Status: `reference-only` · Phase 1 visual motion preview

## Concept

One source line is relayed through four editorial forms while the physical desk remains stable:

`기사 → 뉴스레터 → 짧은 채널 → 영상 대본`

Core line:

> 낮의 장사가 끝난 자리에서, 동네의 두 번째 시간이 시작된다.

## Timing

- Total relay duration: `660ms`
- Four label activations divide the same 660ms total into four 165ms steps.
- Primary easing: `cubic-bezier(.22,.78,.18,1)`
- No bounce, spring, 3D rotation, or viewport travel.

## Animated properties

- `transform`: restrained scale and translate within the paper frame.
- `opacity`: old/new copy and production marks crossfade.
- `clip-path`: image crop changes by format.
- Format labels activate sequentially.
- Proof marks switch from article underline to newsletter rule, short-form crop frame, and script cue bracket.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- all transitions and animations are set to effectively immediate;
- no translation or scale movement occurs;
- state copy, crop, and labels change without travel;
- the replay control remains keyboard operable.

## Review control

The `포맷 릴레이 재생` button restarts the deterministic cycle. It does not generate, edit, or persist content.
