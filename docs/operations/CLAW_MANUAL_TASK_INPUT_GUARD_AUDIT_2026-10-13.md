# Claw manual workflow: remove obsolete 4,000 character pilot ceiling

Scope: the canonical B62 Claw manual-intake preview and executable P01 route,
plus their shared browser composer. These are explicit user-approved, action-
specific quote, order, reply, summary, or extraction workflows, not
the general Claw model-only conversation lane.

Source before: both server routes returned content_too_long for pasted input
longer than 4,000 characters; manual UI independently set textarea maxlength
4,000 and repeated the same arbitrary predicate in preview and execute.
That falsely rejected valid work long before the already-existing executable
P01 intent's own 12,000-character safety contract. It is not a provider
model's native max input tokens.

Source after: both routes use the SAME executable ClawTaskIntent contract
MAX_EXECUTABLE_TASK_CHARS to validate the entire action-prefixed task string,
not just a raw user field. The constant now has one canonical declaration
in kagent.contracts; no alternative authority. The check happens before
session, quota reservation, tenant authorization, artifact generation or P01
execution. Preview and execute are aligned. The browser does not invent its
own 4k character rejection; the server remains authoritative.

The existing 64KiB intake HTTP resource guard is retained; a valid 12k
character UTF-8 human task fits this Worker request budget on the canonical
browser JSON wire. The 100k-character deterministic ManualIntakeRequest
domain guard also remains (never reachable through the narrower executable
P01 tool-task contract). Direct send, memory, quotation amounts, ownership,
user tiers, quota/refund, model registration, approval/resume and structured
artifact controls are unchanged. The general Claw model-only path is
untouched. No long free-form input is silently converted into an unbounded
side-effect/tool execution permission.

Acceptance: RED before fix for 5k+ preview, executed P01 input and browser
cap; GREEN after fix with >4k mixed Unicode content exactly preserved through
the actual route to the P01 adapter once, no truncation; the existing
12k-plus executable tool contract still rejects before quota, malformed
JSON, forbidden channels/actions, body oversize cancellation and untrusted
owner/approval checks unchanged. 145 focused local B62 tests pass.
Linux exact-head CI, GitGuardian and guarded B62 production release must
pass before calling this change deployed.
