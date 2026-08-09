# B1 Personal Edition UI V2 — Issue #443 visual evidence

This directory records the review contract for the owner-rejected B1 UI redesign.
It is **technical browser evidence only** and must not be interpreted as owner UI approval.

## Status boundary

```text
UI_REVIEW_READY
OWNER_UI_APPROVED=false
UX_BLOCKED_BY_UI
BACKEND_FROZEN
PR_OPEN_DRAFT_UNMERGED
DO_NOT_MERGE
```

## Authoritative browser validator

The existing Personal Edition validator is reused without weakening its checks:

```text
apps/personal-edition/docs/visual-review/final/validate_final.py
```

CI checks out the exact pull-request head and runs:

```bash
python docs/visual-review/final/validate_final.py \
  --output-dir "$RUNNER_TEMP/personal-edition-visual-<PR_HEAD_SHA>"
```

The uploaded GitHub Actions artifact is named:

```text
personal-edition-visual-<PR_HEAD_SHA>
```

It contains the validator report/JSON plus exact-viewport screenshots.

## Required viewport matrix

| Viewport | Size |
|---|---:|
| desktop | 1440 × 1100 |
| tablet | 768 × 1024 |
| mobile | 390 × 844 |

The validator captures all three viewports for these review surfaces:

1. entry / hero — `/preview/intro/`
2. participant published home — `/preview/participant/published/`
3. edition reading — `/preview/participant/editions/modal-preview-edition/`
4. feedback / adaptation — `/preview/participant/editions/modal-preview-edition/adaptation/`
5. operator queue — `/admin/`
6. operator participant context — `/admin/participants/modal-preview-user/`
7. operator content review — `/admin/review/modal-preview-edition/content/`
8. operator publish decision — `/admin/review/modal-preview-edition/publish/`

This is 24 deterministic viewport screenshots, exceeding the six-surface minimum in #443 while retaining the operator context screen as additional evidence.

## Browser assertions

The same run also checks:

- real sequential participant journey clicks from intro through adaptation/history
- real sequential operator journey clicks from access through publish decision/feedback continuity
- horizontal overflow at required review surfaces
- console/page/network failures and external requests
- local image/SVG resolution
- focusability and visible keyboard focus
- form labels, button names and link names
- `prefers-reduced-motion: reduce` equivalent state
- source tree remains clean before/after validation
- full Personal Edition pytest suite
- static-preview regression suite

## Approval semantics

A passing artifact means only that the exact PR head is technically reviewable in the tested browsers/viewports. It does not set `OWNER_UI_APPROVED=true`, does not unblock UX by itself, and does not authorize merge or Production replacement.
