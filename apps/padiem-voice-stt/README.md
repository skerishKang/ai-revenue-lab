# padiem-voice-stt

Shared, private Cloudflare Worker that is the single server-side speech-to-text
(STT) authority for **PADIEM Chat (B62)**, **PADIEM Claw (B54)** and
**standalone B66 quotation**.

Owner directive: `ai-revenue-lab#4643` (Chat/Claw) and `ai-revenue-lab#3404`
(B66). Reference implementation: `skerishKang/global-classroom`.

## Why this exists

Global Classroom already runs a proven STT chain. Chat/Claw and B66 must reuse
it, not re-invent it. Global Classroom stays the canonical source of its own
product; this Worker ports only the **runtime-agnostic contract** so PADIEM does
not create a second STT authority.

```text
REUSE: provider order, transcript-event model, utterance identity, dedup rules,
       turn/chunk handling, Groq Whisper transport shape
DO NOT COPY: React hooks, the Netlify function runtime, product UI
```

## Provider order (unchanged)

```text
gemini_live (Gemini Live Transcribe)
  -> browser_speech (browser SpeechRecognition)
    -> groq_whisper (Groq Whisper, server-side)
```

The chain is **one-way within a single microphone run**; it never flaps back to
Gemini after a fallback. Translation/answer models are a different authority and
never substitute for STT here.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/internal/v1/voice/capabilities` | Browser-safe session parameters + provider order. No key, token or account id. |
| `POST` | `/internal/v1/voice/transcribe` | Server-side Groq Whisper transcription of one bounded audio clip. |
| `POST` | `/internal/v1/voice/live-token` | Mints a short-lived, model-locked Gemini Live ephemeral token. The long-lived key never leaves the server. |

The Worker is **private** (`workers_dev = false`). Products reach it over a
Service Binding; the browser never calls it directly.

### Deployment gate

Every route is closed by default. `Default.fetch` resolves
`PADIEM_VOICE_STT_ENABLED` **before** it reads a Secret, builds an upstream
request or performs any paid call. While the flag is not exactly `"true"`, the
whole Worker answers `voice_stt_disabled`. The committed `wrangler.toml` keeps
that flag OFF and `workers_dev = false`, so this Worker cannot serve a browser
today. `workers_dev = false` alone does **not** provide caller authentication,
identity, tenant scope or cost limiting.

### Caller identity, tenant scope and cost approval

A paid route additionally requires a real caller authority, implemented in
`voice_stt_caller_auth.py`. It **reuses the canonical Control Plane** — the same
private Service Bindings `apps/padiem-ai-engine` already uses — so voice spending
is admitted by the same authority as Engine spending instead of a second,
voice-local entitlement system:

| Binding | RPC | What it decides |
|---|---|---|
| `CONTROL_PLANE_IDENTITY` | `resolve_auth_session` | The authenticated subject, whether the session is active/unexpired, and its canonical `tenant_id`. |
| `CONTROL_PLANE_ENGINE_ADMISSION` | `fetch_entitlement_snapshot` | Whether this tenant's product grant includes the voice capability, within its unit limit. |
| `CONTROL_PLANE_ENGINE_ADMISSION` | `reserve_usage` | The per-request cost reservation that admits (or refuses) the call. |

A calling product Worker sends two **opaque clues** — the product it acts for
(`X-Padiem-Product-Id`) and the end user's canonical auth-session id
(`X-Padiem-Auth-Session-Id`). Neither is an identity: they only select which
Control Plane session to resolve. The subject, tenant, entitlement and cost
reservation all come back from the Control Plane. This is the canonical
"opaque server-resolved clue" pattern (#2157/#2158) the Engine already uses.

The order of one paid request is fixed, and each step can only deny:

```text
deployment flag  ->  caller clues  ->  bounded body + audio validation
                 ->  session / tenant  ->  entitlement grant
                 ->  cost reservation  ->  Secret read  ->  provider call
```

The **cost quantity is never client-supplied**: `estimated_units` is computed by
the Worker from the audio length it already validated
(`voice_stt_contract.cost_units_for_audio`, one unit per 256 KiB). There is no
request field for a cap, plan, entitlement or account, and the retired
`VOICE_STT_CALLER_GUARD` binding is no longer read at all — a bound object that
answers `True` or `{"allowed": True, ...}` cannot open a route.

### Activation state: still fail-closed in practice

Neither Control Plane binding is attached to any deployed environment, and the
Control Plane entitlement producer does not yet issue a `voice.stt.*` grant, so
every paid route still fails. What this slice removed is the *absence* of an
implemented gate, not the fail-closed posture:

| Condition | Result |
|---|---|
| flag not exactly `"true"` | `voice_stt_disabled` (503) |
| a Control Plane binding absent, or present without the reviewed RPCs | `caller_guard_unavailable` (503) |
| no clues, blank/malformed clue, unknown or inactive/expired session | `voice_stt_unauthenticated` (401) |
| session or snapshot belonging to another product/subject, non-user subject | `voice_stt_forbidden` (403) |
| session with no `tenant_id`, or one aliased to the product/subject | `voice_stt_tenant_unavailable` (503) |
| no voice grant, grant denied, units over the grant limit, refused or expired reservation | `voice_stt_cost_denied` (403) |
| authority unreachable or answering an unusable shape | `voice_stt_authority_unavailable` (503) |

**Residual boundary, stated rather than hidden.** A Service Binding carries no
built-in caller identity, so the *product* label still comes from the attached
caller. That is acceptable only because the binding is deployment-owned and
because a caller claiming another product can at most spend **its own** Control
Plane tenant's reservation. Deployment therefore requires CENTRAL to review which
Workers hold the binding; the source contract cannot enforce it.

Activation needs, in order: the Control Plane issuing a `voice.stt.transcribe` /
`voice.stt.live_token` grant, the two bindings attached, then the flag. Each is a
CENTRAL decision; none is done here. **Keep the flag OFF.**

### Upstream budget

Each upstream call has **one end-to-end deadline** covering the request *and* the
response body: Groq 25s, Gemini token 8s. The deadline is captured once, the
body read only gets what is left of it, and the body is additionally capped at
`MAX_UPSTREAM_RESPONSE_BYTES` (256 KiB). A provider that answers with headers and
then trickles the body is cut off like any other stall. Both the `AbortSignal`
path and the fallback path (a runtime without `AbortSignal.timeout`) are bounded
by `asyncio.wait_for`, so the ceiling holds on every runtime. The provider
body is read incrementally via `Response.body.getReader()` and refused at
256 KiB + 1 **before** accumulating further bytes; it never uses
`Response.text()` or `Response.json()` (which would materialise an unbounded
response before checking its length).

## Files

| File | Role |
|---|---|
| `voice_stt_contract.py` | The shared contract. Zero dependencies, no `workers` import, unit-testable on CPython. |
| `voice_stt_caller_auth.py` | The canonical Control Plane caller identity / tenant / cost authority for the paid routes. |
| `worker.py` | Thin Cloudflare `workers` adapter over the contract. |
| `wrangler.toml` | Worker config and Secrets Store binding declarations (names only). The sole source of the store resource id. |
| `scripts/build_worker_dependencies.py` | Assembles `.worker-src`; proves the runtime is dependency-free. |
| `tests/fake_workers.py` | In-process stand-in for the Workers runtime and for the two Control Plane bindings. |
| `tests/` | Contract, transport, #87 regression, per-product binding-name, mocked dispatch and adapter-source suites. |

## Secret bindings (names only — never values)

This repository contains no key value; the values stay inside the Cloudflare
Secrets Store. `wrangler.toml` is the only source of the store resource id.

| Binding name | State |
|---|---|
| `PADIEM_GEMINI_API_KEY` | Manifest entry exists in `apps/korean-ai-platform/wrangler.toml`. A manifest entry is **not** runtime verification. |
| `PADIEM_GROQ_API_KEY` | **Owner-reported / inferred, not proven to exist.** No repository manifest entry for Groq exists, no live binding is attached, and no provider availability is implied. Confirm against the live store before the transcribe route can succeed. |

## Gemini Live ephemeral token

`POST /internal/v1/voice/live-token` mints against Google's current REST
reference (`/v1beta/auth_tokens`):

- `expireTime` = now + 30 minutes, `newSessionExpireTime` = now + 1 minute, both
  as **absolute RFC3339 timestamps** (not durations);
- `uses: 1`;
- the STT model is bound through `liveConnectConstraints.model` so the client
  cannot open a Live session against any other model.

This matches the official documentation and the proven
`global-classroom/netlify/functions/live-token.ts`.

## #87 — long-utterance truncation

Global Classroom #87 is still open. This contract is built so PADIEM does not
reproduce it:

- the Live VAD window is **1300ms**, not 650ms, so ordinary thinking pauses stay
  inside one turn (`test_voice_stt_long_utterance_87.py`);
- one Live turn is one row — chunks merge and commit only at the turn boundary;
- the Groq fallback cuts at a **real speech pause** (min 4s, silence 700ms, hard
  max 20s), never at a fixed 5500ms clock;
- a retired session's cached tail is drained with `audioStreamEnd`;
- audio captured during a session rotation is replayed into the new session;
- a re-finalised utterance is dropped by deterministic utterance identity.

## Test

```bash
cd apps/padiem-voice-stt
python -m pytest -q          # 254 tests, no Cloudflare runtime required
```

`tests/test_voice_stt_worker_dispatch.py` drives the real `Default.fetch`
through a fake Workers runtime and fake Control Plane bindings, so the OFF gate,
the caller-authority denials, body bounds, missing keys and malformed inputs are
exercised as behaviour rather than as static string checks. The size boundary is
tested at the **real 5 MiB** `MAX_REQUEST_BYTES` (exact, +1 byte, single
undivided chunk, declared-length lie), not at a small stand-in size.

## Not implemented in this slice

- Chat/Claw microphone UI wiring (blocked by the active `#4488` UI work).
- B66 `#easyVoiceMic` activation.
- The `VOICE_STT_SERVICE` product-side binding (the Service Binding each product
  gains to reach this Worker; not declared because the Worker is not deployed).
- Control Plane issuance of the `voice.stt.transcribe` / `voice.stt.live_token`
  entitlement grant, attachment of the two Control Plane bindings, and flipping
  `PADIEM_VOICE_STT_ENABLED`. All three are CENTRAL activation steps; until they
  happen every paid route answers `voice_stt_cost_denied` or
  `caller_guard_unavailable`.
- B66 is not a Control Plane allowed product (`b62`, `b54-padiem-claw`), so its
  #3404 voice integration has no canonical tenant scope yet and fails closed.
- Deployment, live provider calls and any Secret mutation.
