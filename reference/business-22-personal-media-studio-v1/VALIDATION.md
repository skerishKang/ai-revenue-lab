# Validation — Business 22 Personal Media Studio Phase 1

- Validation date: 2026-07-27
- Phase: `UI_ONLY`
- Workspace: `reference/business-22-personal-media-studio-v1/`
- Required viewports: 1440 × 1100, 768 × 1024, 390 × 844

## Commands executed

```bash
cd reference/business-22-personal-media-studio-v1
python3 tests/validate_static.py
python3 tests/validate_browser.py

cd ../../..
git add reference/business-22-personal-media-studio-v1
git diff --cached --check
```

## Static contract result

`python3 tests/validate_static.py` completed successfully and wrote:

```text
evidence/static-validation.json
```

Verified:

- exactly seven states: `cover`, `sources`, `spine`, `suite`, `adaptation`, `trace`, `mobile`;
- every state token is available to the state router;
- all referenced local assets exist;
- no runtime external URL is present;
- Arrow, Home and End handlers exist for the tab review pattern;
- visible `:focus-visible` treatment exists;
- `prefers-reduced-motion: reduce` is implemented;
- synthetic labels and `UI_ONLY` limitations are visible;
- relay completion, focus preservation and scroll preservation hooks exist.

Result: `PASS`.

## Browser environment

Browser checks used the installed headless Chromium executable:

```text
/usr/bin/chromium
```

This execution environment blocks both localhost HTTP navigation and direct `file://` navigation with `ERR_BLOCKED_BY_ADMINISTRATOR`. The validation therefore loaded the same repository-local HTML, CSS, JavaScript and SVG assets into Chromium using deterministic `page.set_content`, with the assets fully inlined. No product code was changed to accommodate this fallback.

This validates rendered layout, responsive composition, image resolution, state switching, keyboard controls, motion, focus, scroll stability and reduced-motion behavior. It does not independently prove that an HTTP server in this restricted environment can navigate to `?state=` URLs; query parsing is implemented in `app.js` and is covered by the static contract inspection.

## Browser result

`python3 tests/validate_browser.py` completed successfully and wrote:

```text
evidence/validation-report.json
evidence/motion-frames.json
```

### Desktop — 1440 × 1100

All seven states rendered and are preserved as named panels in:

```text
evidence/desktop-states-1440.svg
```

Panels:

```text
desktop-cover-1440
desktop-sources-1440
desktop-spine-1440
desktop-suite-1440
desktop-adaptation-1440
desktop-trace-1440
desktop-mobile-1440
```

For every state:

- active state matched the requested review state;
- primary state surface was visible;
- horizontal overflow: `0`;
- broken images: `0`.

### Tablet — 768 × 1024 and mobile — 390 × 844

Tablet and mobile captures are preserved as named panels in:

```text
evidence/responsive-captures.svg
```

Panels:

```text
tablet-sources-768
tablet-suite-768
tablet-adaptation-768
mobile-cover-390
mobile-suite-390
mobile-mobile-390
```

For every checked state:

- horizontal overflow: `0`;
- broken images: `0`;
- no clipped primary composition or unreadable overlap was detected by deterministic checks and capture review;
- the `mobile` state uses a dedicated vertical edition structure rather than a scaled proof wall.

## Keyboard and focus

The tab review pattern passed:

- Arrow Right moved from `cover` to `sources`;
- focus remained on the corresponding selected tab;
- End moved to `mobile`;
- Home returned to `cover`;
- visible focus treatment is defined for review controls.

Result: `PASS`.

## Signature motion

The `Source-to-Format Relay / 원본 맥락 릴레이` completed at the nominal duration of `720ms`.

Deterministic frame evidence:

```text
evidence/motion-relay-frames.svg
```

Named panels: `motion-frame-00-before`, `motion-frame-01-annotation`, `motion-frame-02-article`, `motion-frame-03-formats`, `motion-frame-04-review`.

Verified:

- the selected source remains fixed;
- the master-story annotation appears first;
- article, audio, video and visual-card adaptations resolve in sequence;
- omission and rewrite notes remain visible;
- the human-review mark resolves last;
- focus remains on the replay control;
- document geometry remains unchanged;
- scroll position remains stable within the browser rounding/timing tolerance recorded in the report.

Result: `PASS`.

## Reduced motion

With `prefers-reduced-motion: reduce`:

- all final relay information was immediately visible;
- replay focus was preserved;
- the final informational state was equivalent to the animated result.

Result: `PASS`.

## Runtime request and error summary

```text
console errors: 0
page errors: 0
failed requests: 0
external requests: 0
broken images: 0
horizontal overflow: 0
```

## Git whitespace check

```bash
git diff --cached --check
```

Result: `PASS`.

## Evidence limitation

The repository does not contain a pre-existing project-level browser harness for this isolated static reference, and this environment disallows browser navigation to localhost and `file://` URLs. The in-memory Chromium fallback is reproducible from `tests/validate_browser.py`, but a later Web CTO review should still open the Draft PR exact head through a normal static server or deployment preview before any `UI_APPROVED` decision.
