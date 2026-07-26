# Story Bloom Motion Specification

## Name

`Story Bloom / 이야기 피어남`

## Narrative purpose

A familiar yellow rain boot remains anchored while layered paper clouds, a folded sail, and a small path emerge around it. The motion communicates that an ordinary lived object can become a fictional motif without showing prompts, models, generation steps, or technical internals.

## Timing

- Total duration: `680ms`
- Easing: `cubic-bezier(0.22, 0.72, 0.18, 1)`
- Boot anchor: stable for the full sequence
- Cloud layers: opacity + vertical travel, `0–520ms`
- Paper sail: opacity + small rotation, `110–620ms`
- Path dots: staggered opacity, `220–680ms`
- Story text, chapter mark, and page position: no movement

## Trigger

- Entering state 7 begins the sequence once.
- The `다시 피우기` review control restarts it.
- The control is a review-only affordance, not accepted UX.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- all layers switch to their final state immediately;
- no translation, rotation, or stagger is applied;
- text and page position remain unchanged;
- the replay control remains keyboard accessible but causes an immediate state refresh.

## Performance and containment

- CSS transforms and opacity only.
- No layout-affecting animation.
- No runtime asset fetch.
- No canvas, video library, external animation package, or requestAnimationFrame loop.
