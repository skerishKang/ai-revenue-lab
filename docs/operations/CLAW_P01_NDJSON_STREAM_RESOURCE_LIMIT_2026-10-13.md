# Claw P01 streamed model answer: incremental limits vs safe memory (2026-10-13)

The opt-in B62 Claw live SSE pathway delegates to the canonical P01 Engine
NDJSON streaming client. This had two separate unconditional 1MiB *cumulative*
stream ceilings: the Cloudflare ENGINE_SERVICE streaming transport and the
Python NDJSON decoder. Further, a 64KiB line limit was imposed on the final
one-line orchestration JSON record, including the user's completed answer.
A healthy long model answer could therefore be falsely rejected mid-run.

The now-reviewed pipeline treats **event bytes** and **one terminal result**
separately, and never counts cumulative healthy model output against a global
1MiB threshold:
* Each intermediate NDJSON event is <=64KiB; <=128 lifecycle events per run.
* Only the Engine's exact canonical terminal envelope key order can use a
  larger single-record safety budget (<=8MiB). All other long records fail
  closed. Terminal result remains unexposed until verified physical EOF.
* The Cloudflare worker bridge bounds individual JS reader chunks at 8MiB,
  yields slices <=64KiB, closes on errors and early cancellation, and lets
  the Python decoder enforce unfinished-line length and event count.
* The decoder slices incoming chunks into <=64KiB pieces itself before
  extending its single-line buffer, preserving memory safety independent of
  transport chunk behavior.
* Existing P01 end-of-stream event-correlation validation, error/refund/usage
  status, owner tier, auth and service-binding credentials, terminal approval
  pause, no-retry/no-fallback, complete JSON non-stream transport and B14
  upstream controls remain unchanged. No model tier is activated.
* Large structured terminal JSON remains finite in a 128MB Worker isolate;
  removal of every memory bound would be unsafe and is not promised here.

Proof: synthetic one-post Service Binding -> real decoder over 1.2M-character
valid terminal; 25 independently small events sum to >1MiB and decode intact;
an oversized terminal line is rejected; a single oversized Worker chunk
is cancelled without reading the next chunk. No real provider calls, no
license, account, model route or production secret changes.


## Completed model transport and long owner context

The same audit found two further mismatches along *actual* generic Claw P01
execution. B62 Engine Service Binding still imposed 256KiB serialized request
and 1MiB completed response, while Claw's previously reviewed owner-history
admission already permits up to a finite 5.5MB context. Engine Python Worker
applied its legacy 128KiB generic non-model ingress guard to all orchestration
requests, even though that Worker already uses the existing 6MB model-execute
body safety budget on its dedicated execution route. This made Claw silently
refuse healthy owner-authenticated long context well before provider execution.

Only the Engine orchestration, resume and opt-in stream endpoints now share
the Engine's existing 6MB bounded model-request ingress; B62 service transport
accepts these matching request sizes. B62 completed orchestration/resume
responses keep a finite 8MiB JSON Worker memory budget, aligned with the
separately reviewed B14 completed JSON safety budget. Other Engine routes,
health, control and connector endpoints retain original 128KiB/256KiB or 1MiB
guards. Existing request identity, credentials, approval and refund semantics
remain unchanged. Production upgrades require independent B62 and Engine
exact-main guarded release gates; no activation or raw API key output.
