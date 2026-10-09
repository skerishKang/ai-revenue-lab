/**
 * Utterance-scoped routing for Interview Live Translate output.
 *
 * A Gemini Live session keeps one continuous conversation history for its whole
 * lifetime, so a translation session that spans several utterances makes
 * utterance N repeat utterance N-1's content. `audioStreamEnd` does not help:
 * the Live API documents it as an end-of-stream/finalisation signal only
 * ("the audio stream paused, flush cached audio"), and the API exposes no field
 * that clears context while the session stays open. The only way to guarantee a
 * clean context is a new session.
 *
 * So translation sessions are recreated on every utterance boundary, and every
 * session is bound to the (utteranceId, generation) pair it was opened for. This
 * module owns that bookkeeping: which utterance a chunk belongs to, and whether
 * it is still allowed to land. It has no network or React dependency so the
 * boundary rules can be tested deterministically.
 */

/** BCP-47 target language code. Kept as a string so #3459 can route more languages. */
export type TranslationTarget = string;

export interface TranslationChunk {
  utteranceId: string;
  generation: number;
  target: TranslationTarget;
  text: string;
  isFinal: boolean;
}

export type UtteranceTranslationEvent =
  | { kind: 'preview'; utteranceId: string; target: TranslationTarget; text: string }
  | { kind: 'final'; utteranceId: string; target: TranslationTarget; text: string };

type Slot = {
  utteranceId: string;
  generation: number;
  targets: Set<TranslationTarget>;
  previews: Map<TranslationTarget, string>;
  finalized: Set<TranslationTarget>;
};

export class InterviewTranslationRouter {
  private readonly emit: (event: UtteranceTranslationEvent) => void;
  private readonly slots = new Map<string, Slot>();
  private activeUtteranceId: string | null = null;

  constructor(emit: (event: UtteranceTranslationEvent) => void) {
    this.emit = emit;
  }

  /** The utterance new translation audio is currently being routed to. */
  get active(): string | null {
    return this.activeUtteranceId;
  }

  /** Start routing output for a new utterance. */
  open(utteranceId: string, generation: number, targets: readonly TranslationTarget[]): void {
    this.slots.set(utteranceId, {
      utteranceId,
      generation,
      targets: new Set(targets),
      previews: new Map(),
      finalized: new Set(),
    });
    this.activeUtteranceId = utteranceId;
  }

  /**
   * Stop routing new audio to the active utterance, but keep its slot writable:
   * a translation that completes late must still land on its own row.
   */
  closeActive(): string | null {
    const closed = this.activeUtteranceId;
    this.activeUtteranceId = null;
    return closed;
  }

  /**
   * Accept one chunk of translation output. Returns false when the chunk is
   * dropped, which happens for output from a forgotten utterance (mic stopped),
   * from a session opened for an older generation, from a target this utterance
   * never asked for, or from a target whose final already landed.
   */
  deliver(chunk: TranslationChunk): boolean {
    const slot = this.slots.get(chunk.utteranceId);
    if (!slot) return false;
    if (slot.generation !== chunk.generation) return false;
    if (!slot.targets.has(chunk.target)) return false;
    if (slot.finalized.has(chunk.target)) return false;

    const text = chunk.text.trim();
    if (!text) {
      // An empty final still settles the target so session teardown can proceed.
      if (!chunk.isFinal) return false;
      slot.finalized.add(chunk.target);
      slot.previews.delete(chunk.target);
      return true;
    }

    if (chunk.isFinal) {
      slot.finalized.add(chunk.target);
      slot.previews.delete(chunk.target);
      this.emit({ kind: 'final', utteranceId: chunk.utteranceId, target: chunk.target, text });
      return true;
    }

    slot.previews.set(chunk.target, text);
    this.emit({ kind: 'preview', utteranceId: chunk.utteranceId, target: chunk.target, text });
    return true;
  }

  /** Latest non-final text for an utterance, used to seed a row before its final lands. */
  previewText(utteranceId: string, target: TranslationTarget): string {
    return this.slots.get(utteranceId)?.previews.get(target) || '';
  }

  isTargetFinal(utteranceId: string, target: TranslationTarget): boolean {
    return this.slots.get(utteranceId)?.finalized.has(target) ?? false;
  }

  hasSlot(utteranceId: string): boolean {
    return this.slots.has(utteranceId);
  }

  /** Drop an utterance once its row can no longer change. */
  forget(utteranceId: string): void {
    this.slots.delete(utteranceId);
  }

  /**
   * Mic stop: every slot is dropped and every later callback becomes a no-op, so
   * a session that is still closing cannot repopulate a cleared conversation.
   */
  invalidate(): void {
    this.slots.clear();
    this.activeUtteranceId = null;
  }
}
