# Central model S3 — trusted pre-dispatch policy inspection (2026-10-12)

## Purpose
An additive, independent **advisory** policy evaluator prepares Chat, Claw, B66 and B14 Router integration without editing their concurrent live handler files. It does not grant a B14 invocation. Caller MUST prove canonical authenticated user, workspace, product membership/tier and P01 capability; the browser cannot assert any of these.

## Source
`apps/padiem-chat/app/central_model_pre_dispatch_advice.py` constructs an exact-model decision from the canonical D1 policy snapshot and B14 registered plus owner-allowed live-ready metadata. The decision is a current snapshot, **not a lease or dispatch authorization**. On invalid/missing D1 or catalog it returns explicit deny (including unknown or OFF model); no fallback.

For a positive snapshot, **both global central and product tier rules must independently allow the requested exact model**. Central OFF overrides product ON. Missing product/tier assignments or B14 offline/readiness fail closed. Only the exact user-selected model is considered.

## Deployment contract / not-yet-implemented
`PreDispatchPolicyDecision.dispatch_authorized` is **always False** in this slice. Product host must re-check before final transport, including revision freshness and its own canonical user/tier/P01 membership. No production product route invokes this evaluator. Source imported only by synthetic tests. Production customer model choices and billing remain unchanged.

To activate any per-product runtime gate:
1. Reconcile the B66 conversation PR #4466 and Claw Connector/P01 work before editing those files.
2. Derive product/tier/owner from the product's canonical server authority, **not** request body or browser tier strings.
3. Add a separate production-controlled OFF-by-default adapter with fail-closed enabled mode. Cover list and dispatch routes, no bypass via alternate endpoint, stream, default model or previously-created conversation.
4. Validate 2+ product/tier combinations and central-OFF priority with exact-model B14 rejection, and add proof of no provider call on deny.
5. Require controlled owner approval for policy grants; existing D1 schema starts empty. Never enable enforcement while missing grants could unintentionally disable current paying customers.
6. Run exact HEAD CI, operator-authorized rollout, prod version/readback and test rollback. Keep `runtime_enforced=false` until all gates pass.

This slice does **not** fix the invalid Worker signing secret in issue #4480. That requires a private Cloudflare console correction; it must not be embedded in source or recorded in logs.
