/**
 * TypeScript port of the shared PADIEM speech-to-text contract.
 *
 * Source of truth: `apps/padiem-voice-stt/voice_stt_contract.py`
 * (contract version `padiem.voice.stt.v1`) in the PADIEM platform repository.
 *
 * The Web voice LOCAL and the native app must agree on the same transcript
 * event model, utterance identity, de-duplication rules, provider fallback
 * order and chunk boundaries. This module is the native half of that contract:
 * it contains no provider key, no provider URL and no new server rule.
 */

export const VOICE_CONTRACT_VERSION = 'padiem.voice.stt.v1';

export type SttProvider = 'gemini_live' | 'browser_speech' | 'groq_whisper';

/** Provider order, preserved from the shared contract. */
export const STT_PROVIDER_ORDER: readonly SttProvider[] = [
  'gemini_live',
  'browser_speech',
  'groq_whisper',
];

/**
 * The next provider in the fallback chain, or `null` at the end.
 *
 * The chain is one-way within a single microphone run: a flapping provider
 * would re-segment an utterance mid-flight.
 */
export function nextProvider(current: SttProvider | null): SttProvider | null {
  if (current === null) {
    return STT_PROVIDER_ORDER[0];
  }
  const index = STT_PROVIDER_ORDER.indexOf(current);
  if (index < 0) {
    return STT_PROVIDER_ORDER[0];
  }
  if (index + 1 >= STT_PROVIDER_ORDER.length) {
    return null;
  }
  return STT_PROVIDER_ORDER[index + 1];
}

export type TranscriptKind = 'interim' | 'final';

export interface TranscriptEvent {
  utteranceId: string;
  kind: TranscriptKind;
  text: string;
  provider: SttProvider;
  language?: string | null;
  sequence: number;
}

export function isAuthoritative(event: TranscriptEvent): boolean {
  return event.kind === 'final' && event.text.trim().length > 0;
}

const MAX_SESSION_ID = 96;
const SAFE_ID_CHARS = /^[A-Za-z0-9._:-]+$/;

/** Deterministic utterance identity: `session:generation:turn`. */
export function makeUtteranceId(
  sessionId: string,
  generation: number,
  turnIndex: number,
): string {
  if (!sessionId || sessionId.length > MAX_SESSION_ID || !SAFE_ID_CHARS.test(sessionId)) {
    throw new Error('invalid session id');
  }
  if (generation < 0 || turnIndex < 0) {
    throw new Error('generation and turnIndex must be non-negative');
  }
  return `${sessionId}:${generation}:${turnIndex}`;
}

/**
 * Merge a chunk that may be a delta or a cumulative hypothesis without
 * duplicating an already-seen prefix or suffix.
 */
export function mergeTranscriptChunk(previous: string, incoming: string): string {
  if (!incoming) {
    return previous;
  }
  if (!previous) {
    return incoming;
  }
  if (incoming.startsWith(previous)) {
    return incoming;
  }
  if (previous.endsWith(incoming)) {
    return previous;
  }
  return previous + incoming;
}

/** One microphone turn is one row: chunks merge, the turn commits at a boundary. */
export class TranscriptTurnBuffer {
  private pending = '';

  get value(): string {
    return this.pending;
  }

  merge(chunk: string | null | undefined): string {
    if (!chunk) {
      return this.pending;
    }
    this.pending = mergeTranscriptChunk(this.pending, chunk);
    return this.pending;
  }

  finishTurn(): string | null {
    const text = this.pending.trim();
    this.pending = '';
    return text.length > 0 ? text : null;
  }

  reset(): void {
    this.pending = '';
  }
}

/** Drop duplicate authoritative finals produced by a fallback or a reconnect. */
export class TranscriptDeduper {
  private committed = new Set<string>();

  accept(event: TranscriptEvent): boolean {
    if (event.kind === 'interim') {
      return true;
    }
    if (this.committed.has(event.utteranceId)) {
      return false;
    }
    this.committed.add(event.utteranceId);
    return true;
  }

  forget(utteranceId: string): void {
    this.committed.delete(utteranceId);
  }

  reset(): void {
    this.committed.clear();
  }
}

/** Ensure one authoritative utterance is submitted at most once. */
export class UtteranceSubmissionGuard {
  private submitted = new Set<string>();

  claim(utteranceId: string): boolean {
    if (this.submitted.has(utteranceId)) {
      return false;
    }
    this.submitted.add(utteranceId);
    return true;
  }

  release(utteranceId: string): void {
    this.submitted.delete(utteranceId);
  }

  has(utteranceId: string): boolean {
    return this.submitted.has(utteranceId);
  }

  reset(): void {
    this.submitted.clear();
  }
}

/** Bounded buffer that keeps a long utterance intact across a session rotation. */
export class AudioHandoffBuffer<T> {
  private frames: T[] = [];
  private capturing = false;
  private dropped = 0;

  constructor(private readonly maxFrames: number) {}

  get size(): number {
    return this.frames.length;
  }

  get droppedFrames(): number {
    return this.dropped;
  }

  get isCapturing(): boolean {
    return this.capturing;
  }

  start(): void {
    this.capturing = true;
  }

  push(frame: T): boolean {
    if (!this.capturing) {
      return false;
    }
    if (this.frames.length >= this.maxFrames) {
      this.dropped += 1;
      return false;
    }
    this.frames.push(frame);
    return true;
  }

  release(): T[] {
    const pending = this.frames;
    this.frames = [];
    this.capturing = false;
    return pending;
  }

  reset(): void {
    this.frames = [];
    this.capturing = false;
  }
}

/** 40 frames cover ~5.1s of connect latency while staying bounded. */
export const LIVE_AUDIO_HANDOFF_FRAMES = 40;

/** Gemini Live automatic activity detection window used by the contract. */
export const GEMINI_LIVE_VAD_SILENCE_MS = 1300;
export const GEMINI_LIVE_SESSION_ROTATE_MS = 9 * 60_000 + 20_000;
export const GEMINI_LIVE_STT_MODEL = 'gemini-3.5-transcribe-live';

/** A stalled turn is committed as-is after this window. */
export const TRANSCRIPT_TURN_STALL_MS = 2500;

/** Groq fallback chunk boundary. */
export const GROQ_MIN_CHUNK_MS = 4000;
export const GROQ_SILENCE_CUT_MS = 700;
export const GROQ_MAX_CHUNK_MS = 20000;

export function shouldFlushStalledTurn(
  hasPending: boolean,
  sinceLastChunkMs: number,
): boolean {
  return hasPending && sinceLastChunkMs >= TRANSCRIPT_TURN_STALL_MS;
}

export function shouldCutGroqChunk(elapsedMs: number, silenceMs: number): boolean {
  if (elapsedMs >= GROQ_MAX_CHUNK_MS) {
    return true;
  }
  if (elapsedMs < GROQ_MIN_CHUNK_MS) {
    return false;
  }
  return silenceMs >= GROQ_SILENCE_CUT_MS;
}

/**
 * Resolve the recognition language.
 *
 * The explicit hint wins, then the language the transcriber actually
 * observed, and only then the device locale. `auto` is skipped rather than
 * treated as a value.
 */
export function resolveRecognitionLanguage(
  hint?: string | null,
  observed?: string | null,
  navigatorLanguage?: string | null,
): string {
  for (const candidate of [hint, observed]) {
    if (candidate && candidate !== 'auto') {
      return candidate;
    }
  }
  return navigatorLanguage || 'ko-KR';
}

/** The shared contract's audio ceiling. */
export const MAX_AUDIO_BYTES = 3 * 1024 * 1024;
export const MAX_REQUEST_BYTES = 5 * 1024 * 1024;

/** Voice conversation modes exposed by the app. */
export type VoiceMode = 'M1' | 'M2' | 'M3' | 'M4';

export const VOICE_MODES: readonly VoiceMode[] = ['M1', 'M2', 'M3', 'M4'];
