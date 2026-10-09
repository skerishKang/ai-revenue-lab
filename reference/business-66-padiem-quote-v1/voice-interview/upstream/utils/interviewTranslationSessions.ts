/**
 * Live Translate session lifecycle for Interview mode.
 *
 * The Gemini Live API keeps a single conversation history per session and
 * exposes no way to clear it while the session stays open, so a translation
 * session that lives for the whole mic session makes every utterance repeat the
 * previous ones. `audioStreamEnd` does not help: the Live API documents it as an
 * end-of-stream/finalisation signal only ("the audio stream paused, flush cached
 * audio"), and the API exposes no field that resets context. The only way to
 * guarantee a clean context is a new session.
 *
 * Isolation therefore comes from a new session per utterance:
 *
 *   active pair  (one per target)  receives the audio of the current utterance
 *   standby pair (one per target)  already connected, no audio, empty context
 *
 * On an utterance boundary the standby pair is promoted, so the next utterance
 * starts on a prewarmed session with no handshake gap, and a fresh standby is
 * opened for the utterance after that. The retired pair is signalled with
 * `audioStreamEnd` so it can still finalise the utterance it already holds, then
 * closed once that lands or once the drain deadline passes.
 *
 * Session count peaks at 2x the number of targets. Set `prewarm: false` to run
 * with one session per target and accept a handshake gap at each boundary.
 */

import {
  InterviewTranslationRouter,
  type TranslationTarget,
} from './interviewTranslationRouter';

export type TranslationMedia = { data: string; mimeType: string };

/** The subset of a Gemini Live session this module uses. */
export interface TranslationSessionHandle {
  sendRealtimeInput(input: { media?: TranslationMedia; audioStreamEnd?: boolean }): void;
  close(): void;
}

export interface TranslationSessionRequest {
  target: TranslationTarget;
  /** `isFinal` is true on turnComplete/generationComplete for that session. */
  onChunk: (text: string, isFinal: boolean) => void;
  onError: (message: string) => void;
  onClose: () => void;
}

export type ConnectTranslationSession = (
  request: TranslationSessionRequest,
) => Promise<TranslationSessionHandle>;

export type InterviewTranslationSessionsOptions = {
  targets: readonly TranslationTarget[];
  connect: ConnectTranslationSession;
  onUtteranceStart: (utteranceId: string) => void;
  onPreview: (utteranceId: string, target: TranslationTarget, text: string) => void;
  onFinal: (utteranceId: string, target: TranslationTarget, text: string) => void;
  onWarning?: (message: string) => void;
  prewarm?: boolean;
  /** Hard bound on how long a retired session may stay open. */
  drainTimeoutMs?: number;
  /** How long a finished utterance still accepts late output before it is forgotten. */
  forgetAfterMs?: number;
  /** Cap on reconnect attempts for a single utterance, to avoid a hot loop. */
  maxReconnectsPerUtterance?: number;
  createUtteranceId?: () => string;
  setTimer?: (handler: () => void, ms: number) => number;
  clearTimer?: (id: number) => void;
};

type Entry = {
  target: TranslationTarget;
  handle: TranslationSessionHandle;
  utteranceId: string;
  generation: number;
  text: string;
  state: 'active' | 'standby' | 'draining';
  reconnects: number;
  retiring: boolean;
};

const DEFAULTS = {
  prewarm: true,
  drainTimeoutMs: 8000,
  forgetAfterMs: 30_000,
  maxReconnectsPerUtterance: 2,
};

let utteranceCounter = 0;

function defaultUtteranceId(): string {
  const globalCrypto = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (typeof globalCrypto?.randomUUID === 'function') return globalCrypto.randomUUID();
  utteranceCounter += 1;
  return `utterance-${Date.now().toString(36)}-${utteranceCounter}`;
}

export class InterviewTranslationSessions {
  private readonly options: InterviewTranslationSessionsOptions &
    Required<
      Pick<
        InterviewTranslationSessionsOptions,
        'prewarm' | 'drainTimeoutMs' | 'forgetAfterMs' | 'maxReconnectsPerUtterance'
      >
    >;

  private readonly router: InterviewTranslationRouter;
  private readonly entries = new Set<Entry>();
  private readonly activeByTarget = new Map<TranslationTarget, Entry>();
  private readonly standbyByTarget = new Map<TranslationTarget, Entry>();
  private readonly connectingActive = new Set<TranslationTarget>();
  private readonly connectingStandby = new Set<TranslationTarget>();
  private readonly forgetTimers = new Map<string, number>();
  private readonly setTimer: (handler: () => void, ms: number) => number;
  private readonly clearTimer: (id: number) => void;
  private readonly createUtteranceId: () => string;

  private generation = 0;
  private running = false;

  constructor(options: InterviewTranslationSessionsOptions) {
    this.options = { ...DEFAULTS, ...options };
    this.setTimer = options.setTimer ?? ((handler, ms) => setTimeout(handler, ms) as unknown as number);
    this.clearTimer = options.clearTimer ?? ((id) => clearTimeout(id));
    this.createUtteranceId = options.createUtteranceId ?? defaultUtteranceId;

    this.router = new InterviewTranslationRouter((event) => {
      if (event.kind === 'final') {
        this.options.onFinal(event.utteranceId, event.target, event.text);
      } else {
        this.options.onPreview(event.utteranceId, event.target, event.text);
      }
    });
  }

  get activeUtteranceId(): string | null {
    return this.router.active;
  }

  previewText(utteranceId: string, target: TranslationTarget): string {
    return this.router.previewText(utteranceId, target);
  }

  /** Connect the first utterance. Resolves true when at least one target is live. */
  async start(): Promise<boolean> {
    if (this.running) return this.activeByTarget.size > 0;
    this.running = true;

    const utteranceId = this.createUtteranceId();
    this.generation += 1;
    this.router.open(utteranceId, this.generation, this.options.targets);
    this.options.onUtteranceStart(utteranceId);

    await Promise.all(this.options.targets.map((target) => this.openEntry(target, 'active', utteranceId)));
    if (this.options.prewarm) this.prewarmStandbys();

    return this.running && (this.activeByTarget.size > 0 || this.connectingActive.size > 0);
  }

  /** Route one audio chunk to the sessions of the current utterance only. */
  feedAudio(media: TranslationMedia): void {
    for (const entry of this.activeByTarget.values()) {
      try {
        entry.handle.sendRealtimeInput({ media });
      } catch {
        // onError/onClose own the recovery path.
      }
    }
  }

  /**
   * Close the context boundary between two utterances. Returns the utterance
   * that just finished, so the caller can attach its source row to it.
   */
  rotate(): string | null {
    const finished = this.router.closeActive();

    // retire() removes each entry from activeByTarget; the standby pair is
    // deliberately left in place so ensureActive() can promote it.
    for (const entry of [...this.activeByTarget.values()]) this.retire(entry);

    const utteranceId = this.createUtteranceId();
    this.generation += 1;
    this.router.open(utteranceId, this.generation, this.options.targets);
    this.options.onUtteranceStart(utteranceId);

    for (const target of this.options.targets) this.ensureActive(target);
    if (this.options.prewarm) this.prewarmStandbys();

    return finished;
  }

  /** Mic stop: drop every pending utterance and make outstanding callbacks inert. */
  stop(): void {
    this.running = false;
    for (const id of this.forgetTimers.values()) this.clearTimer(id);
    this.forgetTimers.clear();

    for (const entry of [...this.entries]) this.closeEntry(entry);
    this.activeByTarget.clear();
    this.standbyByTarget.clear();
    this.connectingActive.clear();
    this.connectingStandby.clear();
    this.entries.clear();
    this.router.invalidate();
  }

  private prewarmStandbys(): void {
    for (const target of this.options.targets) {
      if (this.standbyByTarget.has(target) || this.connectingStandby.has(target)) continue;
      this.openEntry(target, 'standby', null);
    }
  }

  private ensureActive(target: TranslationTarget): void {
    const standby = this.standbyByTarget.get(target);
    if (standby) {
      this.standbyByTarget.delete(target);
      standby.state = 'active';
      standby.retiring = false;
      standby.text = '';
      standby.reconnects = 0;
      standby.utteranceId = this.router.active || '';
      standby.generation = this.generation;
      this.activeByTarget.set(target, standby);
      return;
    }

    // A connection opened before this boundary has no audio yet, so its context
    // is empty; it simply serves whichever utterance is current when it lands.
    if (this.connectingActive.has(target)) return;
    this.openEntry(target, 'active', this.router.active);
  }

  private openEntry(
    target: TranslationTarget,
    state: 'active' | 'standby',
    utteranceId: string | null,
    reconnects = 0,
  ): Promise<void> {
    const inFlight = state === 'active' ? this.connectingActive : this.connectingStandby;
    if (inFlight.has(target)) return Promise.resolve();
    inFlight.add(target);

    let entry: Entry | null = null;

    const request: TranslationSessionRequest = {
      target,
      onChunk: (text, isFinal) => {
        if (entry) this.handleChunk(entry, text, isFinal);
      },
      onError: (message) => {
        this.options.onWarning?.(`실시간 ${target} 번역 연결 오류: ${message}`);
        if (entry) this.handleDropped(entry);
      },
      onClose: () => {
        if (entry) this.handleDropped(entry);
      },
    };

    return this.options
      .connect(request)
      .then((handle) => {
        inFlight.delete(target);
        if (!this.running) {
          safeClose(handle);
          return;
        }

        entry = {
          target,
          handle,
          utteranceId: state === 'standby' ? '' : utteranceId || this.router.active || '',
          generation: this.generation,
          text: '',
          state,
          reconnects,
          retiring: false,
        };
        this.entries.add(entry);

        if (state === 'standby') {
          // A standby that lost the race to a rotation is no longer needed.
          if (this.standbyByTarget.has(target)) {
            this.closeEntry(entry);
            return;
          }
          this.standbyByTarget.set(target, entry);
        } else {
          this.activeByTarget.set(target, entry);
        }
      })
      .catch((error: unknown) => {
        inFlight.delete(target);
        this.options.onWarning?.(
          `실시간 ${target} 번역 세션을 열지 못했습니다: ${error instanceof Error ? error.message : String(error)}`,
        );
      });
  }

  private handleChunk(entry: Entry, text: string, isFinal: boolean): void {
    if (entry.state === 'standby' || !text) return;

    entry.text = mergeStreamText(entry.text, text);
    const accepted = this.router.deliver({
      utteranceId: entry.utteranceId,
      generation: entry.generation,
      target: entry.target,
      text: entry.text,
      isFinal,
    });
    if (isFinal) entry.text = '';
    if (!accepted) return;

    if (this.router.isTargetFinal(entry.utteranceId, entry.target)) {
      this.scheduleForget(entry.utteranceId);
    }
  }

  /** An unexpected drop: drop the entry, and rebuild the active one if it still matters. */
  private handleDropped(entry: Entry): void {
    if (entry.retiring) {
      this.closeEntry(entry);
      return;
    }
    const wasActive = entry.state === 'active';
    this.removeEntry(entry);
    if (!this.running || !wasActive) return;
    if (entry.reconnects >= this.options.maxReconnectsPerUtterance) return;
    if (!this.router.active) return;

    this.openEntry(entry.target, 'active', this.router.active, entry.reconnects + 1);
  }

  private retire(entry: Entry): void {
    entry.retiring = true;
    entry.state = 'draining';
    if (this.activeByTarget.get(entry.target) === entry) this.activeByTarget.delete(entry.target);

    // Documented meaning: the audio stream paused, flush cached audio. This is
    // what lets a retired session finalise the utterance it already holds. It
    // does not reset the session's context, which is why the session is replaced.
    try {
      entry.handle.sendRealtimeInput({ audioStreamEnd: true });
    } catch {
      // The session is being torn down regardless.
    }

    this.setTimer(() => this.closeEntry(entry), this.options.drainTimeoutMs);
  }

  private closeEntry(entry: Entry): void {
    this.removeEntry(entry);
    safeClose(entry.handle);
    if (this.router.hasSlot(entry.utteranceId)) this.scheduleForget(entry.utteranceId);
  }

  private removeEntry(entry: Entry): void {
    this.entries.delete(entry);
    if (this.activeByTarget.get(entry.target) === entry) this.activeByTarget.delete(entry.target);
    if (this.standbyByTarget.get(entry.target) === entry) this.standbyByTarget.delete(entry.target);
  }

  /**
   * Keep a finished utterance accepting late output for a bounded window, so a
   * completion that arrives out of order still lands on its own row.
   */
  private scheduleForget(utteranceId: string): void {
    if (this.forgetTimers.has(utteranceId)) return;
    const id = this.setTimer(() => {
      this.forgetTimers.delete(utteranceId);
      this.router.forget(utteranceId);
    }, this.options.forgetAfterMs);
    this.forgetTimers.set(utteranceId, id);
  }
}

function safeClose(handle: TranslationSessionHandle | null | undefined): void {
  try {
    handle?.close?.();
  } catch {
    // no-op
  }
}

/**
 * Live transcription events can be cumulative revisions or incremental chunks.
 * Kept identical to the previous implementation so scoping a session to one
 * utterance does not change how a single utterance's text is assembled.
 */
function mergeStreamText(previous: string, incoming: string): string {
  if (!incoming || !incoming.trim()) return previous;
  if (!previous) return incoming.trimStart();

  const previousTrimmed = previous.trimEnd();
  const incomingTrimmed = incoming.trimStart();

  if (incomingTrimmed.startsWith(previousTrimmed)) return incomingTrimmed;
  if (previousTrimmed.endsWith(incomingTrimmed)) return previous;

  if (/\s$/.test(previous) || /^\s/.test(incoming)) return previous + incoming;
  const needsBoundary =
    /[A-Za-z0-9가-힣]$/.test(previous) && /^[A-Za-z0-9가-힣]/.test(incoming);
  return `${previous}${needsBoundary ? ' ' : ''}${incoming}`;
}
