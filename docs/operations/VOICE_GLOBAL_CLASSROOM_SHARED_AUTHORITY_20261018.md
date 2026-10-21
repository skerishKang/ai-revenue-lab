# Shared voice authority — Global Classroom port and product reuse contract

Effective 2026-10-18. Applies to Chat, Claw, B66 Padiem Quote and meeting capture (#4647).
Owner of the authority file: the #4643 voice lane. This document records the contract;
it does not grant any product new permissions, providers or usage limits.

## 1. The authority

`apps/padiem-chat/static/voice-live-transcript-turn.js` is a verbatim JavaScript translation
of `utils/liveTranscriptTurn.ts` at `skerishKang/global-classroom`
`ffa27e6a93605614031fed314ef33571c85b8f18` (the file added by the Global Classroom #87 fix
commit `8c61e0d9`). Only TypeScript notation was removed. Values, comparisons and side
effects are the original's, and the original's own gates run against them
(`apps/padiem-chat/tests/voice_live_transcript_turn_4643.cjs`, hosted by
`tests/test_voice_live_transcript_turn_4643.py`).

The reason this file exists is Global Classroom issue #87: two diverging copies of the
transcription turn logic produced "one long sentence, several partial rows". A second copy
anywhere in PADIEM re-opens that defect.

| Export | Responsibility |
| --- | --- |
| `LIVE_TRANSCRIBE_MODEL`, `LIVE_VAD_SILENCE_MS`, `LIVE_SESSION_ROTATE_MS`, `LIVE_AUDIO_HANDOFF_FRAMES`, `LIVE_TAIL_FLUSH_DRAIN_MS`, `GROQ_*`, `TRANSCRIPT_TURN_STALL_MS` | the measured timing contract |
| `mergeLiveTranscriptChunk` | accept delta or cumulative hypotheses without duplicating a seen prefix/suffix |
| `createTranscriptTurnBuffer` | one turn accrues chunks; only the boundary commits one row |
| `shouldFlushStalledTurn` | a boundary that never arrives must not hold a turn forever |
| `shouldCutGroqChunk` | cut a fallback chunk at a speech pause, not at a fixed clock |
| `startSpeechSilenceProbe` | local RMS pause detection for a MediaRecorder stream |
| `createAudioHandoffBuffer` | capture microphone frames during a session swap, replay in order, count drops |
| `flushLiveTranscriptTail` | finalise the audio a retired session still holds before closing it |
| `resolveRecognitionLanguage` | hint → observed source → browser locale |

## 2. Product boundaries

The authority owns microphone timing, chunking, turn identity and session hand-off. It never
sends, stores, authorises or bills. Each product keeps its own seams:

| Product | Uses the authority | Keeps product-local | Status |
| --- | --- | --- | --- |
| Chat / Claw | via `static/voice-stt-input.js`, loaded first by `static/index.html` | `voice-composer.js` run identity and IME deferral, `voice-stt-wiring.js` same-origin `/api/voice/transcribe` transport and the `/api/voice/identity` account check, existing Send | wired and gated |
| B66 Quote | bundle built from the upstream TypeScript copy | `voice-quote-bridge.js`, the B66 token route | contract only, see §3 |
| Meeting #4647 | planned replacements named below | `meeting-capture.js` MediaRecorder artifact, ledger writes, Drive receipts | contract only, see §3 |

## 3. Pending consumers, with the exact measured gap

**B66 (`reference/business-66-padiem-quote-v1`, PR #3763).** Its `voice-interview/PROVENANCE.json`
pins Global Classroom `299c8e7830f6e4aa0c5202ca5591f240487c5c38` (2026-10-08, PR #83), which
predates `utils/liveTranscriptTurn.ts` — that path returns 404 at the pinned commit. The vendored
`upstream/hooks/useInterviewLive.ts` therefore carries the pre-#87 engine:
`silenceDurationMs: 650` (lines 418, 480), a fixed `}, 5500);` recorder stop (line 305) and
`recognition.lang = navigator.language || 'ko-KR'` (line 333). Global Classroom's own
`tests/unit/interviewTranscriptionTurn87.test.ts` asserts all three literals must be absent.
Required before B66 voice is called a reuse of the validated engine: advance the pin to
`ffa27e6a…`, add `upstream/utils/liveTranscriptTurn.ts` to the provenance file list, rebuild the
bundle, and re-run the provenance probes.

**Meeting capture (`apps/padiem-chat/static/meeting-capture.js`).** Three behaviours are the
pre-#87 shape, and each has an authority replacement:

- `recognizer.lang = "ko-KR"` (line 74) → `resolveRecognitionLanguage({ hint, observed, navigatorLanguage })`.
- restart after `onend` with a blind 350 ms timer (lines 97-108) and no tail flush → the retired
  recognizer must be drained with `flushLiveTranscriptTail` and the reconnect gap captured with
  `createAudioHandoffBuffer` / `LIVE_AUDIO_HANDOFF_FRAMES`, or a sentence in flight at the restart
  is lost — the measurement in the original's source comment is 51/64 words recovered without the
  signal against 62/64 with it.
- `lines.push(value)` guarded by `committedIndices` (lines 79-86) → `createTranscriptTurnBuffer`,
  which emits one row per boundary instead of one row per result index.

The existing `MAX_AUDIO_BYTES` stop is a bounded-artifact rule for the recording file, not a
transcription turn rule; it stays where it is and is not moved into the authority.

## 4. Rules for any new consumer

- Import the authority. Do not restate a constant, a merge rule or a turn boundary locally;
  `voice_live_transcript_turn_4643.cjs` counts copies and fails on an unlisted one.
- Do not add a usage quota, a per-day count or a second billing rule here. Cost admission stays
  with the existing STT worker and Control Plane entitlement checks.
- Do not select a new STT engine or model provider from this file; provider choice is owner-only
  and stays in the worker/entitlement lane.
- TTS default is the browser `speechSynthesis` primitive (`static/voice-tts-output.js`). The
  Global Classroom external TTS route is not the PADIEM default path.
