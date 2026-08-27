# Implementation self-check

This evidence is generated from exact local source bytes for the implementation branch. It is not detached-worktree localhost validation, independent Local Validation, Web CTO approval or user UI approval.

## Commands

```bash
python tests/validate_reference.py
python tests/browser_self_check.py
```

## Expected contract

- exact states: 7;
- tabs/panels: 7/7;
- reciprocal ARIA: 7/7;
- keyboard navigation contract: ArrowLeft, ArrowRight, Home, End;
- viewports: 1440×1100, 768×1024, 390×844;
- matrix: 21 combinations;
- horizontal document overflow: 0;
- broken local assets: 0;
- console/page errors: 0;
- failed/external requests: 0;
- nominal final animationend completion: 760ms;
- replay equality, focus, scroll and geometry stability;
- reduced-motion immediate completion;
- persistent boundaries: 7/7.

## Maintained status

```text
UI_REVIEW_READY
NOT_VALIDATED_BY_LOCAL
NOT_DEPLOYED_PENDING_UI_APPROVAL
UX_NOT_STARTED
BACKEND_FROZEN
PR_OPEN_DRAFT_UNMERGED
DO_NOT_MERGE
```
