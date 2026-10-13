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
whole Worker answers `voice_stt_disabled`.

`ON` is additionally gated on the `VOICE_STT_CALLER_GUARD` Service Binding, which
does not exist yet, so this Worker cannot be switched on today. That binding is
what must supply an authenticated caller identity and a bounded per-account cost
authorization. `workers_dev = false` alone does **not** provide caller
authentication, identity or rate limiting.

Binding **presence alone only opens the key-free `capabilities` route.** The two
paid routes are then **unconditionally fail-closed** with
`caller_authorization_unimplemented` (503):
`worker._require_caller_authorization` never returns and never calls the binding.

Why it never returns: there is no production service-binding authorization
contract, so nothing a binding says can be verified as caller identity or cost
reservation. A previous revision consulted the binding and accepted a bare
`True`, an `{"allowed": True, ...}` verdict or an unscoped positive — which let a
request reach a Secret and a paid provider without an identified caller. That is
exactly what is now refused by not asking at all:

| Guard shape | Result |
|---|---|
| binding absent | `caller_guard_unavailable` (503) |
| binding present, any shape (empty, approving, denying, `True`, `{}`, blank/zero scope, self-declared account) | `caller_authorization_unimplemented` (503) — the binding is never invoked |

No client-supplied header, no method-name fallback and no dummy account permit
can change this. A paid route becomes reachable only when a real caller
authority is implemented in its own integration slice and hands the Worker a
`voice_stt_contract.CallerAuthorization` (authenticated actor + tenant + exact
route + per-request cost reservation). Until then: **keep the flag OFF.**

The paid pipeline behind the gate (request shape, budgets, provider masking) is
covered by tests that build that authorization object by hand; the Worker itself
can never obtain one.

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
| `worker.py` | Thin Cloudflare `workers` adapter over the contract. |
| `wrangler.toml` | Worker config and Secrets Store binding declarations (names only). The sole source of the store resource id. |
| `scripts/build_worker_dependencies.py` | Assembles `.worker-src`; proves the runtime is dependency-free. |
| `tests/fake_workers.py` | In-process stand-in for the Workers runtime, so the real dispatch path is testable on CPython. |
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
python -m pytest -q          # 196 tests, no Cloudflare runtime required
```

`tests/test_voice_stt_worker_dispatch.py` drives the real `Default.fetch`
through a fake Workers runtime, so the OFF gate, the paid-route closure, body
bounds, missing keys and malformed inputs are exercised as behaviour rather than
as static string checks. The size boundary is tested at the **real 5 MiB**
`MAX_REQUEST_BYTES` (exact, +1 byte, single undivided chunk, declared-length
lie), not at a small stand-in size.

## Not implemented in this slice

- Chat/Claw microphone UI wiring (blocked by the active `#4488` UI work).
- B66 `#easyVoiceMic` activation.
- The `VOICE_STT_SERVICE` and `VOICE_STT_CALLER_GUARD` bindings (the caller guard
  is what makes paid routes reachable and does not exist yet). Both paid routes
  are unconditionally fail-closed with `caller_authorization_unimplemented`,
  whatever the binding says, until a real caller authority supplies a verified
  `CallerAuthorization`.
- Deployment, live provider calls and any Secret mutation.
