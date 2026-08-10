# B16 — Personal Sports Visual Direction

Status: `DIRECTION_FROZEN`  
Verdict: `REDESIGN_ART_LAYER`

Preserve `MATCHDAY → FOCUS → FLOW → MOMENTS` and current interaction contracts. Replace the shared dark giant-title family with a sports-specific temporal surface.

`OWNER_UI_APPROVED=false` remains unchanged.

## Evidence

Fresh platform audit run `31422928265`, artifact `9076118820`, canonical `https://16-personal-sports.pages.dev/`. Current root uses a ~136px condensed title and dark diagram language similar to B15/B21/B22.

## Product thesis

A fan follows one match as an authored sequence of focus, flow and memorable moments rather than a generic score dashboard.

Core object: **the match clock / momentum timeline and marked moments**.

## Reserved territory — Matchday Broadcast Journal

- scoreboard/time rail used sparingly
- pitch/court/field geometry only when sport-specific
- momentum/timeline strip
- moment cards anchored to exact match time
- broadcast-note / fan-journal hybrid
- one active team/match accent

Avoid generic sports betting dashboard, stat wall, neon dark poster and social feed.

## Key surfaces

- Matchday: fixture/clock/context immediate.
- Focus: selected match theme/player/sequence.
- Flow: momentum/timeline is primary.
- Moments: saved/marked moments attached to time.

## Differentiation

B16 is temporal live-match journaling. B18 is audio playback timeline. B13 is viewed-media archive.

## Acceptance criteria

1. match/time context visible in first viewport;
2. timeline/momentum replaces abstract diagram as focal object;
3. moments attach to exact game time;
4. no B15/B21/B22 dark-poster collision;
5. Mobile shows match context and first meaningful event early;
6. sports data remains synthetic/bounded as current contract requires.
