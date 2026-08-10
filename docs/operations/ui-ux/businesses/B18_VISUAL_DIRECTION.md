# B18 — Personal Audio Channel Visual Direction

Status: `DIRECTION_FROZEN`  
Verdict: `REDESIGN_ART_LAYER`

Preserve listening/echo interaction and queue/player contracts. Replace the first-impression dark giant-title family with a product-specific listening environment.

`OWNER_UI_APPROVED=false` remains unchanged.

## Evidence

- fresh publication-family audit run `31422640921`, artifact `9076026735`
- canonical `https://18-personal-audio-channel.pages.dev/`
- existing flow remains technically coherent, but root visually collides with B10/B12: dark field + oversized English display + small abstract audio object.

## Product thesis

A personal listening queue becomes a paced private listening room where the user plays, leaves an echo/reaction and keeps selected moments.

```text
QUEUE → PLAY → ECHO → KEEP → RETURN
```

Core object: **the current track and its listening timeline**, not a poster headline.

## Reserved visual territory

**Listening Room / Audio Timeline**

- waveform/timeline with real hierarchy
- track artwork or generative audio identity as secondary support
- current time / duration / chapter markers
- quiet acoustic spatial depth
- echo/reaction moments anchored to playback positions
- queue visible as a listening sequence, not cards

Avoid generic streaming-service clone, neon equalizer spectacle, black poster shell, podcast dashboard and B13 video contact-sheet language.

## Reference translation

Adopt from strong listening interfaces:
- current audio object has clear temporal position
- queue and current item remain oriented
- annotations/reactions attach to a moment rather than float as comments

Reject:
- platform branding/social metrics
- endless recommendation feed
- oversized decorative waveform with no control meaning

Translate:
- the user sees a compact personal room where playback time and their own echoes create the archive.

## Key surfaces

- Queue: sequence and next-up rhythm.
- Player: primary visual object, with time and controls in first viewport.
- Echoes: reactions attached to exact moments.
- Keep: saved moment/track state clearly visible.
- Mobile: player + first echo visible early; queue follows.

## Differentiation

- B13 = visual cinema ledger; B18 = temporal audio listening trace.
- B10/B12 = editorial publication/production; B18 = playback and time.

## Acceptance criteria

1. player/timeline becomes first-viewport core object;
2. queue and echo positions are spatially/temporally clear;
3. current dark giant-title composition is no longer the primary identity;
4. interaction flow and reset behavior remain intact;
5. Mobile prioritizes playback before decorative title treatment;
6. visually distinct from B10/B12/B13 at thumbnail distance.
