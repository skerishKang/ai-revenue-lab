/**
 * #3140 — the main-process consumer of the bounded pairing handoff.
 *
 * #3095 built the handoff and the one-shot out
 * (`ShellController.takePairingHandoffForRunner()`), but nothing in the main
 * flow ever called it: the deep link armed the handoff and the code sat in the
 * controller. This module is that missing caller. It is the *only* place the
 * pairing code leaves the main process, and it hands it to exactly one
 * destination: the supervised runner, which is the only process trusted to see
 * it.
 *
 *   MAIN_FLOW_CONSUMES_HANDOFF=YES
 *   HANDOFF_CONSUMED_EXACTLY_ONCE=YES
 *   PAIRING_CODE_RENDERER_EXPOSURE=0
 *   PAIRING_CODE_LOGGED=0
 *   PAIRING_CODE_GENERAL_PERSISTENCE=0
 *   PAIRING_AUTHORITY_IMPLEMENTED=NO    <-- #3080 remains the only authority
 *   RESIDENT_HOST_IMPLEMENTED=NO        <-- #3014 remains the only host
 *
 * The consumer holds no copy of the code. It calls the controller's one-shot
 * `take()`, writes the envelope over the supervised channel, and immediately
 * drops the value. When the runner is not live the handoff is *left armed*:
 * `take()` is not called at all, so a deep link that arrives before the runner
 * starts is still deliverable once it is. That is the difference between
 * "delivered once" and "discarded once", and only the first is correct.
 */

import { createHash } from 'node:crypto';

import { pairingHandoffConsumedMarker } from '../contract/pairing-deeplink.js';

/**
 * The non-reversible digest an acknowledgement echoes back, so delivery can be
 * correlated exactly without the code ever leaving the one-shot.
 */
export function handoffDeliveryMarker(pairingCode: string): string {
  return createHash('sha256').update(`delivery.v1:${pairingCode}`).digest('hex').slice(0, 32);
}


/**
 * The two-phase handoff source.
 *
 * `peek` must not consume and must not mark the handoff spent; `commit` is
 * reached only once the destination is known to have received the envelope.
 */
export interface PairingHandoffSource {
  peekPairingHandoffForRunner(): { pairingCode: string; correlationRef: string } | null;
  commitPairingHandoffDelivery(): { pairingCode: string; correlationRef: string } | null;
}

/**
 * The supervised channel to the resident host.
 *
 * #3140 review A: a successful `write` is *not* a delivery acknowledgement.
 * Writing to a pipe only proves the bytes were handed to the OS. The resident
 * acknowledges receipt itself, so delivery is a two-message exchange: write, then
 * wait for a bounded, secret-free ACK whose correlation matches the handoff
 * that was sent. A timeout, a child exit or an unparsable ACK is a refusal, and
 * the one-shot stays armed.
 */
export type PairingHandoffDeliverer = (
  line: string,
) => Promise<{ readonly acknowledged: boolean; readonly handoffMarker: string | null }>;

export type PairingHandoffOutcome =
  | 'delivered'
  | 'no_pending_handoff'
  | 'runner_unavailable'
  | 'delivery_refused'
  | 'ack_timeout'
  | 'ack_rejected'
  | 'ack_mismatch';

export interface PairingHandoffConsumerStats {
  readonly deliveredCount: number;
  readonly lastOutcome: PairingHandoffOutcome;
  /** Non-reversible marker of the last delivered handoff. Never the code. */
  readonly lastDeliveredMarker: string | null;
  readonly pairingCodeRetained: false;
}

/** #3140: the widest handoff envelope the main process will write. */
export const MAX_HANDOFF_LINE_CHARS = 4_096;

export const PAIRING_HANDOFF_CONTRACT = Object.freeze({
  MAIN_FLOW_CONSUMES_HANDOFF: true,
  HANDOFF_CONSUMED_EXACTLY_ONCE: true,
  PAIRING_CODE_RENDERER_EXPOSURE: 0,
  PAIRING_CODE_LOGGED: 0,
  PAIRING_CODE_GENERAL_PERSISTENCE: 0,
  PAIRING_AUTHORITY_IMPLEMENTED: false,
  RESIDENT_HOST_IMPLEMENTED: false,
  EXECUTION_AUTHORITY_IMPLEMENTED: false,
  SECOND_PAIRING_AUTHORITY: 0,
  PUBLIC_INBOUND_PORT: 0,
} as const);

export class PairingHandoffConsumer {
  readonly #source: PairingHandoffSource;
  readonly #deliver: PairingHandoffDeliverer;
  readonly #isRunnerLive: () => boolean;
  #deliveredCount = 0;
  #lastOutcome: PairingHandoffOutcome = 'no_pending_handoff';
  #lastDeliveredMarker: string | null = null;

  constructor(options: {
    readonly source: PairingHandoffSource;
    readonly deliver: PairingHandoffDeliverer;
    /** Whether the destination can receive the line now, starting it if needed. */
    readonly isRunnerLive: () => boolean;
  }) {
    this.#source = options.source;
    this.#deliver = options.deliver;
    this.#isRunnerLive = options.isRunnerLive;
  }

  /**
   * Deliver a pending handoff to the runner, at most once.
   *
   * Returns the outcome so the caller can report truthfully. The handoff is
   * taken only when the runner can actually receive it: an unavailable runner
   * leaves the handoff armed for the next attempt instead of burning it.
   */
  async deliverPending(nowMs: number = Date.now()): Promise<PairingHandoffOutcome> {
    void nowMs;
    if (!this.#canDeliver()) {
      this.#lastOutcome = 'runner_unavailable';
      return this.#lastOutcome;
    }
    // Phase one: look without consuming. A failed delivery must leave the
    // one-time code armed so a later attempt can still deliver it.
    const pending = this.#source.peekPairingHandoffForRunner();
    if (pending === null) {
      this.#lastOutcome = 'no_pending_handoff';
      return this.#lastOutcome;
    }
    const line = JSON.stringify({
      contract_version: 'claw-desktop-pairing-handoff.v1',
      pairing_code: pending.pairingCode,
      correlation_ref: pending.correlationRef,
    });
    if (line.length > MAX_HANDOFF_LINE_CHARS) {
      this.#lastOutcome = 'delivery_refused';
      return this.#lastOutcome;
    }
    // The marker proves which handoff the ACK is about without echoing the
    // code: a non-reversible digest, same idea as the #3095 replay ledger.
    const marker = handoffDeliveryMarker(pending.pairingCode);
    let acknowledgement: { readonly acknowledged: boolean; readonly handoffMarker: string | null };
    try {
      acknowledgement = await this.#deliver(line);
    } catch {
      // Nothing was consumed: the handoff is still pending and retryable.
      this.#lastOutcome = 'delivery_refused';
      return this.#lastOutcome;
    }
    if (acknowledgement.acknowledged === false) {
      this.#lastOutcome = 'ack_timeout';
      return this.#lastOutcome;
    }
    if (acknowledgement.handoffMarker === null) {
      this.#lastOutcome = 'ack_rejected';
      return this.#lastOutcome;
    }
    if (acknowledgement.handoffMarker !== marker) {
      // An ACK for some other handoff is not an ACK for this one.
      this.#lastOutcome = 'ack_mismatch';
      return this.#lastOutcome;
    }
    // Phase two, and only now: the destination acknowledged the exact handoff.
    this.#source.commitPairingHandoffDelivery();
    this.#deliveredCount += 1;
    this.#lastDeliveredMarker = pairingHandoffConsumedMarker(pending.pairingCode);
    this.#lastOutcome = 'delivered';
    return this.#lastOutcome;
  }

  /** Secret-free. Safe for status, logs and the renderer. */
  stats(): PairingHandoffConsumerStats {
    return Object.freeze({
      deliveredCount: this.#deliveredCount,
      lastOutcome: this.#lastOutcome,
      lastDeliveredMarker: this.#lastDeliveredMarker,
      pairingCodeRetained: false as const,
    });
  }

  #canDeliver(): boolean {
    return this.#isRunnerLive();
  }
}
