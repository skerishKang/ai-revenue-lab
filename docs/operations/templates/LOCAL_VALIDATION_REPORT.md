# Local Validation Report

## 1. Validation identity

- Repository:
- Pull Request:
- Branch:
- Expected HEAD SHA:
- Actual tested HEAD SHA:
- Validation date/time and timezone:
- Validator:
- Workflow status: `LOCAL_PASSED` / `LOCAL_FAILED`

Expected and actual HEAD must match. If they do not match, stop and report the mismatch.

## 2. Environment

- OS/version:
- CPU/GPU:
- Runtime versions:
- Browser/version:
- Desktop viewport:
- Mobile viewport:
- Dependency installation method:
- External services used:
- Mock/staging/real mode:

Do not include secret values.

## 3. Repository state

```text
git rev-parse HEAD
<output>

git status --short
<output>
```

- Pre-existing dirty files:
- Source files modified during validation: yes / no
- If yes, exact files and reason:

If product source code was modified, this report cannot assign `LOCAL_PASSED`. Return the changes to the Web Developer as a separate implementation step.

## 4. Setup and execution

| Step | Command/action | Exit/status | Result |
|---|---|---:|---|
| Setup |  |  |  |
| Build |  |  |  |
| Run |  |  |  |
| Tests |  |  |  |

Include relevant stdout/stderr excerpts for failures.

## 5. Acceptance flow validation

| Flow | Expected | Actual | Result |
|---|---|---|---|
|  |  |  | PASS / FAIL |

## 6. Browser and UI evidence

### Desktop

- URL:
- Viewport:
- Core flow result:
- Horizontal overflow:
- Screenshot/video artifact:

### Mobile

- URL:
- Viewport:
- Core flow result:
- Horizontal overflow:
- Screenshot/video artifact:

### Runtime errors

- Console errors:
- Page errors:
- Failed requests:
- Unexpected warnings:
- Loading/empty/error/success states:
- Keyboard/focus observations:

## 7. External integration evidence

- Provider/service/database:
- Endpoint or environment:
- Request/response contract:
- Timeout/retry behavior:
- Authentication/authorization behavior:
- Secret non-disclosure confirmed:
- Data creation/deletion/rollback impact:

## 8. Failures

For each failure:

- Expected result:
- Actual result:
- Exact command or action:
- Error/status:
- Minimal reproduction:
- Relevant log excerpt:
- Hypothesis, clearly marked as unverified:

## 9. Final local verdict

- Status: `LOCAL_PASSED` / `LOCAL_FAILED`
- Tested HEAD:
- Blocking failures:
- Non-blocking observations:
- Required developer follow-up:

This is an environment-validation result, not the final CTO merge status.
