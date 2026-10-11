# PADIEM Product Language & Visual System V1

Status: CENTRAL authority draft
Scope: Padiem Website, Padiem Chat, Padiem Claw
Owner: Web/CENTRAL

## 1. Product-family rule

Padiem Website, Padiem Chat, and Padiem Claw are one product family.

Claw is not an independently themed product.

- CLAW_OWNS_THEME = NO
- CLAW_INHERITS_CHAT_THEME = YES

Claw may own layout, workflow-specific components, information density, and task affordances. It must not create a separate palette, dark surface system, typography system, radius system, shadow system, or theme switch.

## 2. Canonical theme policy

Current source contains five theme identifiers: padiem-glass, padiem-home, light, dark, cinematic.

The long-term user-facing model should be simplified.

### Primary product theme

The default product identity is Padiem.

Implementation may continue to use the current internal padiem-glass / padiem-home names during migration, but the user-facing product should not require users to understand internal historical theme variants.

### Optional appearance modes

Recommended user-facing modes:

1. Padiem — brand-default, bright/neutral/glass-led.
2. Light — accessibility-oriented bright mode.
3. Dark — accessibility/preference dark mode.

### Cinematic

Cinematic interaction is a motion/atmosphere property, not a requirement that the whole application become near-black.

The existing cinematic palette is intentionally very dark (#04070d base in current source). It may remain as an internal/reference mode while migration is underway, but should not define the default Padiem product identity.

- DEFAULT_NEAR_BLACK_UI = NO
- CINEMATIC_MOTION != BLACK_THEME

## 3. Shared visual tokens

Chat owns the shared application theme. Claw consumes those tokens.

Required shared semantic tokens:

- --bg
- --page-bg
- --panel
- --card-bg
- --card-border
- --text
- --muted
- --line
- --accent
- --accent-soft
- --accent-strong
- --danger
- --focus-ring
- --shadow
- --composer-bg
- --composer-border
- --topbar-bg

### Claw prohibition

Do not introduce Claw-only semantic aliases for shared color roles.

Deprecated / avoid:

- --ink
- --text-muted
- hard-coded near-black workspace colors
- hard-coded white surfaces that bypass active theme
- Claw-only dark/cinematic palettes

Use the canonical Chat token for the same semantic role.

## 4. Visual-family acceptance rules

Website, Chat, and Claw do not have to be pixel-identical. They must share typography family and hierarchy principles, neutral/pearl/glass surface language, accent family, border softness, radius logic, restrained shadows, interaction polish, language controls, brand naming, and accessible contrast.

### Claw-specific visual character

Claw should feel like a focused work surface, not a developer console.

Preferred character:

- bright or neutral default canvas;
- strong document readability;
- restrained glass or pearl panels;
- charcoal text;
- Padiem accent for focus/action;
- compact task controls;
- optional dark mode inherited from Chat.

## 5. Theme inheritance contract

Every Claw component must render correctly under the same active root theme as Chat.

Required matrix:

- Padiem default
- Light
- Dark

During migration, legacy cinematic and padiem-home / padiem-glass aliases may still be tested to prevent regressions.

Changing the Chat theme must change Claw without a second Claw preference.

- ONE_THEME_PREFERENCE = YES
- CLAW_THEME_PREFERENCE = NONE

## 6. Language policy

Supported product languages for this phase are ko and en.

The user must be able to switch language explicitly.

Preferred behavior:

- explicit KR/EN selector;
- preserve explicit language in the URL (`?lang=ko|en`) so reloads and shared links remain deterministic;
- do not use localStorage/sessionStorage for locale preference under the current browser-persistence privacy contract;
- a future trusted account preference may become the cross-product persistence authority after a separate approval;
- no IP-based forced language;
- no separate Claw language setting;
- Chat and Claw use the same active locale;
- website language alignment may be connected later through a shared preference contract.

- ONE_CHAT_CLAW_LOCALE = YES
- GEOIP_FORCED_LANGUAGE = NO

## 7. Copy policy

Product names remain untranslated: Padiem, Padiem Chat, Padiem Claw.

User-facing copy must prefer natural product language over literal translation.

| English | Korean |
|---|---|
| Workspace | 작업공간 |
| Project | 프로젝트 |
| Run | 실행 |
| Retry | 다시 시도 |
| Result | 결과 |
| Preview | 미리보기 |
| Approval | 승인 |
| Evidence | 근거 |
| Connector | 커넥터 / 연결 서비스, depending on surface |
| Save | 저장 |
| Download | 다운로드 |

Technical documentation may use the English canonical term in parentheses on first use.

## 8. Error-state language

Failures must be truthful.

Never render a failed backend/network/malformed response as success.

Never echo user input into a result container in a way that looks like AI/backend output.

Error copy should state what failed at the user level, whether retry is safe, and what the user can do next.

Avoid internal stack/runtime vocabulary in ordinary product copy.

## 9. Documentation ownership

Language, UI copy, glossary, user guides, and visual policy are Web/CENTRAL-owned editorial artifacts.

Local implementation agents implement approved keys and tokens, must not invent replacement product copy, must not create a new visual language, and must not rename canonical product concepts without CENTRAL review.

## 10. Current source observations

Current Padiem Chat source already provides ko / en locale dictionaries, a shared settings language selector, multiple theme variants, padiem-glass as current default in theme-init.js, and Claw as a first-class workspace inside the Chat shell.

The current source also retains historical theme complexity and legacy Claw aliases. This document defines the convergence direction rather than claiming that convergence is already complete.

## 11. Implementation acceptance criteria

A convergence PR is acceptable when:

- Claw uses only Chat semantic theme tokens for shared color roles;
- no independent Claw theme switch exists;
- default Claw appearance visually matches active Chat theme;
- KO/EN key sets are complete and meaning-equivalent;
- no user-facing hard-coded KO/EN text remains where locale switching is expected;
- desktop and 390px mobile render correctly;
- light/dark/default contrast meets WCAG AA for normal text;
- console/page errors remain zero;
- existing truthful preview/error-state behavior remains intact.

## 12. Separation from Engine work

- UI_THEME_LANGUAGE_DOCS_ONLY = YES
- ENGINE_RUNTIME_CHANGE = NO
- PRODUCTION_MUTATION = 0