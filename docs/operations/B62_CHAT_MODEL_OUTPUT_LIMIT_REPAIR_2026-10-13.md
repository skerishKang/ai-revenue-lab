# B62 Chat output limits - exact-scoped repair (2026-10-13)

The regular B62 text chat, image-model reply and tool-grounded answer use
the shared Core completed B14 client. B14 production already accepts a
finite 8MiB completed-JSON raw-body memory budget, but the B62 Core client
still used the unrelated original 1MiB collector default. More importantly,
the B62-to-B14 Cloudflare Service Binding adapter also applied an independent
1MiB cap before the result reached either B62 or B66. The B66 quote-only
client repair #4579 was therefore NOT sufficient to pass a >1MiB response
in production until the Service Binding adapter was also corrected.

This change aligns the B62 completed Core path and the common completed
Service Binding read to the EXISTING safe B14/Core maximum without disabling
finite server-RAM protection. Incremental SSE paths are unchanged and
continue to allow long cumulative generation; there is no new token or
character cap and no implicit stream=false to stream=true format change.
A successful fully buffered model response still needs finite memory limits
in a 128MB shared Worker isolate.

The B62 final deep-research answer used to send an arbitrary
max_tokens=1500; it now omits that model-generation ceiling. The separate
research query PLANNER continues to have its 300-token bounded
three-query JSON task budget, not a user-visible answer ceiling.

Safety/authority retained: user auth, product-tier registration and HOLD,
model/provider authorization, no external model fallback, same-origin,
usage quota, 6MB inbound transport guard, 5.5MB owned history/extra context
transport guard, untrusted-document/evidence isolation, source citations,
network resource idle/timeout protections, and individual SSE frame size
guard. No B62 Plus/Pro/Max HOLD model becomes executable from this change.
No model secret or database mutation. B66 quote original guard remains
unchanged and now gets the same Common Worker bridge resource envelope.

Regression proofs use synthetic local B14 binding/HTTP bodies, never a paid
provider call. 1.2M ASCII completed model content exact roundtrip on
ordinary Chat path, >2MiB physical Service Binding exact read, cap+1
body fails early with cancellation, and deep-research final TaskMode does
not set max_tokens. Full B62 CI, GitGuardian, and exact-main protected
production readback are required to declare release complete. Real
authenticated customer-tier inference remains separately gated by
explicit Owner-approved provider registration, not by code assumptions.
