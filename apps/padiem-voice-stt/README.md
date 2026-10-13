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
| `POST` | `/internal/v1/voice/live-token` | Mints a short-lived Gemini Live ephemeral token. The long-lived key never leaves the server. |

The Worker is **private** (`workers_dev = false`). Products reach it over a
Service Binding; the browser never calls it directly.

## Files

| File | Role |
|---|---|
| `voice_stt_contract.py` | The shared contract. Zero dependencies, no `workers` import, unit-testable on CPython. |
| `worker.py` | Thin Cloudflare `workers` adapter over the contract. |
| `wrangler.toml` | Worker config and Secrets Store binding declarations (names only). |
| `scripts/build_worker_dependencies.py` | Assembles `.worker-src`; proves the runtime is dependency-free. |
| `tests/` | Independent contract, transport, #87 regression, binding-name and adapter-source suites. |

## Secret bindings (names only — never values)

The Worker reuses the existing PADIEM Cloudflare Secrets Store
(`f0b09ca04a7b43248154c773704a5616`). No new key is created, requested, read,
printed or returned.

| Binding name | State |
|---|---|
| `PADIEM_GEMINI_API_KEY` | Verified: already declared in `apps/korean-ai-platform/wrangler.toml`. |
| `PADIEM_GROQ_API_KEY` | **NOT RUNTIME-VERIFIED.** Owner reports a Groq key exists; the exact `secret_name` is absent from every repository `wrangler.toml`. Confirm before deploy. Until then the transcribe route fails closed with `stt_key_missing`. |

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
python -m pytest -q          # 65 tests, no Cloudflare runtime required
```

## Not implemented in this slice

- Chat/Claw microphone UI wiring (blocked by the active `#4488` UI work).
- B66 `#easyVoiceMic` activation.
- The `VOICE_STT_SERVICE` Service Binding on `apps/padiem-chat/wrangler.toml`
  (needs this Worker deployed first).
- Deployment, live provider calls and any Secret mutation.
