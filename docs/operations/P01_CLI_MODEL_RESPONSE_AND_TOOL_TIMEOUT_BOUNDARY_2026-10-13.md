# P01 CLI model response budget and independent timeout ownership

The P01 standalone CLI UrllibEngineTransport independently rejected any
successful orchestrate model reply above 1MiB, a pilot-era buffer guard.
The previously deployed B62/Engine model result path now safely accepts
8MiB completed JSON. This CLI-only adapter was still behind that budget.

This update uses Core's existing MAX_CONFIGURED_B14_RESPONSE_BYTES (8MiB)
for successful POST to exactly Engine model-execute, orchestrate and
orchestrate-resume. Health, cancel, non-model routes, non-2xx error replies
and non-incremental streaming endpoint retain the old 1MiB bounded read.
At most limit+1 bytes are ever buffered and larger responses explicitly
fail, preserving the existing p01_engine_response_too_large error. No token
limit, API activation, approval bypass, retry or fallback is introduced.

Timeout separation audit: P01 UrllibEngineTransport 3600-second socket
timeout is a connect/read resource watchdog, distinct from P01 Engine
ExecutionContext default 900s/max 3600s execution budget. Tool/agent steps
use await_with_agent_progress with an inactivity watchdog; a progressing
tool plan is not subject to a single total run cutoff. Core's single-shot
model-only execution still has a distinct asyncio.wait_for(context timeout)
and the upstream B14 completed transport still has a finite resource
timeout. Neither is lifted without an authenticated streamed-progress
or recoverable durable-operation contract. This CLI response memory fix
must not be described as an elimination of all model total time limits.

Synthetic proof: one >1.3MiB healthy model JSON reply round-trips verbatim,
8MiB+1 fails closed, unrelated health or stream endpoints and HTTP errors
still fail at the small original budget. GitHub KAgent Windows/Linux checks
and security are mandatory. No provider request or customer secret involved.
