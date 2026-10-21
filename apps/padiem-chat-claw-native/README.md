# PADIEM Chat & Claw - native Android client

A React Native Android application for PADIEM Chat and PADIEM Claw.

This app is **not** a WebView wrapper and it is **not** a second platform. It is
a native client that speaks the **existing** PADIEM server contracts, so the
same account, the same session, the same AI tier rules, the same model
selection and the same Claw authority apply on Android exactly as they do on
the web.

## What it reuses (no new server, no new auth, no new model rule)

| Concern | Existing contract |
|---|---|
| Session | `padiem_session` cookie issued by the existing auth layer |
| Google sign-in | `POST /auth/android/handoff` -> `GET /auth/android/handoff/{id}` -> `POST /auth/android/handoff/{id}/claim` |
| Password sign-in | `POST /api/auth/password/login` |
| Session state | `GET /api/auth/status`, `POST /api/auth/logout` |
| AI tier (model selection) | `GET`/`PUT /api/account/model-selection` (`allowed_tiers`, `admin_available`) |
| Chat answer | `POST /api/chat/stream` (SSE: `delta` / `done` / `error`) |
| Chat answer with a file | `POST /api/chat` (`application/octet-stream` framed payload) |
| Conversation history | `GET /api/conversations`, `GET /api/conversations/{id}`, `DELETE` |
| Claw composer | `POST /api/claw/general` (canonical P01 Engine lane) |
| Claw PC state | `GET /api/claw/local-access`, `/api/claw/local-access/devices`, `.../devices/select`, `.../connect` |
| Claw runs | `GET /api/claw/runs`, `POST /api/claw/approvals/decision` |
| Voice | `GET /api/voice/identity`, `POST /api/voice/transcribe` (Claw: `/api/claw/voice/*`) |

The app never decides whether a tier is allowed, whether a PC is reachable, or
whether a Claw run may proceed. It renders what the server reported.

## Native session handling

The web client keeps the session in a browser cookie jar. A native HTTP client
has no such jar, so this app stores the **value** of the `padiem_session`
cookie and replays it as a `Cookie` request header. The credential, its
signature and its server-side authority are unchanged; only the transport that
carries it differs.

React Native 0.86 exposes `set-cookie` to JavaScript and uses OkHttp's
`JavaNetCookieJar` natively, so the claim response's cookie is captured
directly - no third-party cookie module is needed.

## Streaming

React Native's `fetch` has no readable response body, so the SSE transport is
built on `XMLHttpRequest`, whose `responseText` grows while the request is
still LOADING. The frame grammar is the server's own grammar
(`apps/padiem-chat/app/chat_routes.py::_public_sse`).

## Voice

`src/voice/voiceContract.ts` is a TypeScript port of the shared PADIEM
speech-to-text contract (`padiem.voice.stt.v1`,
`apps/padiem-voice-stt/voice_stt_contract.py`). It carries the transcript
event model, the deterministic utterance identity, the de-duplication rules,
the provider fallback order and the chunk boundaries, so this client and the
web voice client agree on the same state machine. The app holds **no** provider
key: the captured audio is forwarded to the existing PADIEM voice route.

## Layout

```
src/
  api/        server contract, native HTTP client, SSE transport
  auth/       session storage + sign-in context
  state/      shared conversation state (messages, tier, mode)
  components/ composer, message bubble, tier picker, sidebar, Claw panel
  screens/    login, chat (Chat+Claw), history, settings
  voice/      shared STT contract, native bridge, voice controller
  i18n/       Korean-first copy (ko/en)
  ui/         theme with system dark-mode support
```

Chat and Claw share **one** conversation screen. The product switch only
decides which existing server lane the answer is requested from; the layout,
the composer, the tier picker and the history are the same code.

## Build

The toolchain lives on `D:` so the `C:` system drive keeps headroom.

```powershell
. D:\PADIEM\projects\padiem-chat-claw-native\setup-env.ps1
cd android
.\gradlew.bat :app:assembleRelease "-PreactNativeArchitectures=arm64-v8a"
```

`setup-env.ps1` points `TEMP`/`TMP`/`TMPDIR`, `ANDROID_HOME`,
`GRADLE_USER_HOME` and `NPM_CONFIG_CACHE` at `D:` and pins JDK 17.

Requirements: Node >= 22.11, JDK 17, Android SDK platform 36 + build-tools
36.0.0 + NDK 27.1.12297006 + CMake 3.22.1.

## Current state

Implemented and wired to the live server: sign-in (Google handoff and
password), session persistence, sign-out, account-scoped tier selection, the
shared Chat/Claw conversation screen with streaming answers, conversation
history with search and delete, the Claw PC panel (connection state, device
selection, run list, approval), file attachment selection, and the voice
contract with the M1-M4 modes.

Still open: the native microphone/text-to-speech module, the binary upload
path for attachments, and on-device verification.
