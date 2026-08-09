# Meaning Ripple Motion Specification

## Intent

The Meaning Ripple visualizes how selecting one remembered item changes emphasis around it without replacing the whole map or disorienting the viewer.

## Trigger

- Enter the `Meaning Ripple / 의미 파동` review state.
- Select a representative item.
- Activate `의미 파동 다시 보기`.

## Sequence

Total target duration: **680ms**.

1. `0–120ms` — selected item receives an ink-ring emphasis.
2. `80–480ms` — three contour rings expand from the selected item with restrained opacity.
3. `180–620ms` — related fragments reveal in a fixed semantic order: place → person → event.
4. `420–680ms` — connecting rules sharpen and the explanation strip settles.
5. Surrounding fragments remain visible at reduced emphasis throughout.

## Implementation boundary

- CSS transforms and opacity only.
- JavaScript only restarts a deterministic CSS class and updates representative selection copy.
- No physics engine, canvas library, data ranking, generated relationships, or persistence.

## Reduced motion

Under `prefers-reduced-motion: reduce`:

- no spatial travel, ring expansion, stagger, or animated reordering;
- the selected, related, and explanation states appear immediately;
- orientation marks and surrounding context remain unchanged.
