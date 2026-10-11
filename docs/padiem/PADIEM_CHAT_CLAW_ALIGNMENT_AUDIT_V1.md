# PADIEM Chat / Claw Alignment Audit V1

Status: Web/CENTRAL implementation audit
Baseline main: 8c038f671165086e709c58c8c9ae84c3a2955ea3
Website authority source: skerishKang/18-padiemai
Application authority source: skerishKang/ai-revenue-lab

## 1. Correct product-family model

The public website and the product application do not need identical background colors.

Canonical split:

- Padiem Website = dark cinematic brand world.
- Padiem Chat = product application with its own appearance system; current default is padiem-glass.
- Padiem Claw = workspace inside Padiem Chat; it inherits the active Chat theme.

Therefore:

- BRAND_CONTINUITY != IDENTICAL_BACKGROUND
- CLAW_INHERITS_CHAT_THEME = YES
- CLAW_INDEPENDENT_THEME = NO

## 2. Website visual authority

The current 18-padiemai visual grammar defines the public website authority as:

- dark navy-black / graphite around #06080d;
- pearl/frosted glass;
- white/silver typography;
- Padiem blue #88c9ff;
- warm gold #efc984;
- SUIT/SUITE + Manrope;
- editorial Korean typography;
- thin translucent rules;
- large negative space;
- cinematic media and restrained motion.

These are family-brand signals. Chat/Claw should carry compatible typography, glass/material cues, accent signals and restraint without forcing the product workspace onto a black homepage canvas.

## 3. Chat current theme authority

Current theme-init.js supports:

- padiem-glass (default)
- padiem-home
- light
- dark
- cinematic

Current default is padiem-glass.

That means Claw should render under whichever root data-theme Chat is already using. A second Claw theme state is not required.

## 4. Claw visual debt measured on baseline

Current main Claw styles still contain independent color decisions.

Measured baseline:

- claw-workspace.css: 13 unique hard-coded hex colors detected;
- claw-manual-intake.css: 4 unique hard-coded hex colors detected;
- legacy/shared-role aliases include --ink and --text-muted;
- several fallbacks hard-code #111a22, #5b6672, #fff and other product-local colors.

Not every hex literal is automatically wrong: semantic status colors or accessibility fallbacks may remain when justified. Shared surface/text/accent roles must move to Chat semantic theme tokens.

Required convergence:

- shared text -> --text;
- secondary text -> --muted;
- shared borders -> --line / --card-border;
- shared surfaces -> --card-bg / --panel;
- active control -> --accent / --accent-strong;
- focus -> --focus-ring;
- errors -> --danger;
- shadows -> --shadow or approved shared shadow tokens.

## 5. Language audit

locale.js currently has exact top-level key parity:

- KO keys = 213
- EN keys = 213
- KO-only keys = 0
- EN-only keys = 0

This proves dictionary parity, but not full UI localization coverage.

Static-source scan on the baseline found:

- index.html: 87 Korean hard-coded string/attribute suspects outside data-locale-key;
- app.js: 105 unique Korean string suspects.

These are audit candidates, not an assertion that all 192 occurrences are bugs. They include runtime error text, aria labels, placeholders, dynamic confirmations, hidden/disabled UI and developer-adjacent messages.

Required review classification for each candidate:

1. USER_VISIBLE_LOCALIZE
2. ACCESSIBILITY_LOCALIZE
3. RUNTIME_STATUS_LOCALIZE
4. INTERNAL_ONLY_KEEP
5. TEST_OR_DEPRECATED_IGNORE

## 6. Implementation split

To reduce hot-file risk, #2489 should be implemented in two serialized source slices after PR #2487 disposition.

### Slice A — Theme inheritance

Target:

- Claw shared visual roles use Chat tokens;
- no Claw theme preference;
- padiem-glass / light / dark / legacy cinematic all inherit coherently;
- truthful #2483 error behavior preserved;
- no broad redesign of Chat.

Primary files likely include:

- apps/padiem-chat/static/claw-workspace.css
- apps/padiem-chat/static/claw-manual-intake.css
- bounded tests.

index.html / app.js / locale.js should be avoided in Slice A unless strictly required.

### Slice B — Full KO/EN coverage

Target:

- classify hard-coded user-facing strings;
- migrate required strings to locale keys;
- preserve exact KO/EN key parity;
- localize aria labels, placeholders, runtime messages, confirmations and visible status text;
- Chat and Claw share one active locale.

Primary files likely include:

- apps/padiem-chat/static/index.html
- apps/padiem-chat/static/app.js
- apps/padiem-chat/static/locale.js
- locale coverage tests.

## 7. Docs integration

User guides already exist under docs/padiem.

Do not create a new product navigation hierarchy solely to expose them. Add a docs/help entry only if an existing Help/Settings/About surface provides a natural destination.

## 8. Acceptance matrix

Theme inheritance:

- Padiem default: PASS
- Light: PASS
- Dark: PASS
- legacy Cinematic regression: PASS
- no second Claw theme state: PASS

Language:

- KO dictionary key parity: PASS
- EN dictionary key parity: PASS
- visible Claw KO coverage: PASS
- visible Claw EN coverage: PASS
- Chat critical-path visible coverage: PASS
- aria/placeholder parity: PASS

Regression:

- #2483 truthful error state preserved
- input echo never presented as AI/backend output
- desktop PASS
- 390px PASS
- console errors 0
- page errors 0

## 9. Ownership

- visual and copy authority = Web/CENTRAL;
- local agents may implement an approved bounded slice only;
- local agents must not invent new terminology, theme architecture or product copy;
- Engine/Core/B14 changes are out of scope.

PRODUCTION_MUTATION=0