# Validation — Business 22 Personal Media Studio Phase 1

- Validation date: 2026-07-28
- Phase: `UI_ONLY`
- Workspace: `reference/business-22-personal-media-studio-v1/`
- Required viewports: 1440 × 1100, 768 × 1024, 390 × 844
- Signature motion contract: 680–760ms

## Commands executed

```bash
cd reference/business-22-personal-media-studio-v1
python3 tests/validate_static.py
python3 tests/validate_browser.py

git diff --check
git diff --cached --check
```

## Static contract

`python3 tests/validate_static.py` passed and regenerated:

```text
evidence/static-validation.json
```

Verified:

- exactly seven visual states;
- every state query token exists;
- all local asset paths exist;
- no runtime external URL;
- UI timing label is 740ms;
- CSS final motion end is computed as 740ms;
- final completion uses `.step-review` `animationend`;
- no fixed completion `setTimeout remains;
- replay explicitly enters `running` and finishes at `complete`;
- keyboard tab controls, visible focus and reduced-motion rules remain present;
- synthetic labels and UI_ONLY limitations remain visible.

Result: `PASS`.

## Browser environment

```text
/usr/bin/chromium
headless Chromium
fully inlined page.set_content harness
```

The execution environment blocks localhost and `file://` navigation. The validation script therefore inlines the repository-local HTML, CSS, JavaScript and SVG assets into Chromium. It records zero external runtime requests.

## Responsive validation

### 1440 × 1100

All seven states resolved:

```text
cover
sources
spine
suite
adaptation
trace
mobile
```

### 768 × 1024

```text
sources
suite
adaptation
```

### 390 × 844

```text
cover
suite
mobile
```

Across validated viewports:

```text
horizontal overflow: 0
broken images: 0
console errors: 0
page errors: 0
failed requests: 0
external runtime requests: 0
```

Keyboard review controls passed for ArrowRight, Home and End, including focus movement to the selected tab.

## Computed motion timing

The browser test reads `getComputedStyle()` for every relay step and calculates `animation-delay + animation-duration`.

| Step | Delay | Duration | Computed end |
|---|---:|---:|---:|
| annotation | 80ms | 120ms | 200ms |
| rule | 180ms | 120ms | 300ms |
| article | 280ms | 120ms | 400ms |
| audio | 380ms | 120ms | 500ms |
| video | 460ms | 120ms | 580ms |
| visual card | 540ms | 120ms | 660ms |
| human review | 620ms | 120ms | **740ms** |

Assertion:

```text
680 <= computedFinalEndMs <= 760
680 <= 740 <= 760
PASS
```

The report no longer contains a manually assigned nominal duration.

## Relay state and stability

Immediately after replay:

```text
data-motion-state == running
PASS
```

After the final review animation event:

```text
data-motion-state == complete
PASS
```

The following remained stable:

```text
focus: replay
scrollX: 0
scrollY: 20
document height: 1140px
source x/y/width/height: unchanged
human-review mark: visible
```

Result: `PASS`.

## Reduced motion

With `prefers-reduced-motion: reduce`:

```text
all relay steps immediately visible: PASS
human-review mark visible: PASS
state complete: PASS
focus replay retained: PASS
scroll unchanged: PASS
document height unchanged: PASS
source geometry unchanged: PASS
```

## Evidence regenerated

```text
evidence/motion-relay-frames.svg
evidence/motion-frames.json
evidence/validation-report.json
evidence/static-validation.json
```

`validate_browser.py` also revalidated all required desktop, tablet and mobile states. Static viewport layout and source assets were not changed by this timing correction, so the existing viewport evidence files remain the visual baseline.

## Machine-readable summary

`evidence/validation-report.json` reports:

```text
allQueriesResolve: true
zeroHorizontalOverflow: true
zeroBrokenImages: true
zeroConsoleErrors: true
zeroPageErrors: true
zeroFailedRequests: true
zeroExternalRequests: true
keyboardPassed: true
motionPassed: true
reducedMotionPassed: true
```

## Phase limitation

This remains a static `UI_ONLY` visual reference. It does not implement upload, generation, recording, playback, editing, saving, export, publishing, authentication, persistence, API, database, backend or deployment.
