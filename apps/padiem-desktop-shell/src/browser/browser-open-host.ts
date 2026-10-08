/**
 * #3611 — trusted-main `browser.open` host (open-only).
 *
 * This module is the whole authority of the slice:
 *
 *   BROWSER_OPEN_IMPLEMENTED = true
 *   BROWSER_CONTROL_IMPLEMENTED = false
 *   PERSISTENT_PROFILE_SUPPORTED = false
 *   PAGE_DERIVED_OUTPUT_SUPPORTED = false
 *
 * It owns no Electron API. The ephemeral view is injected through
 * `BrowserOpenViewPort`; the only Electron-touching module is
 * `browser-open-electron-view.ts`, which implements that port.
 *
 * Flow: validate the approved request -> re-validate the canonical URL -> bind the
 * one-shot grant -> refuse if the host is unconfigured -> navigate exactly the
 * approved URL with a per-navigation policy gate -> bounded receipt -> always close.
 */

import {
  BROWSER_OPEN_DEFAULT_TIMEOUT_MS,
  BROWSER_OPEN_HOST_REF,
  BROWSER_OPEN_MAX_REDIRECTS,
  BROWSER_OPEN_MAX_TTL_SECONDS,
  BrowserOpenContractError,
  assertApprovedBrowserOpenRequest,
  assertBoundedUrl,
  buildBrowserOpenReceipt,
  type ApprovedBrowserOpenRequest,
  type BrowserOpenLoadOutcome,
  type BrowserOpenReceipt,
} from './browser-open-contracts.js';
import { isNavigationPermitted, isPermittedPublicUrl } from './public-url-policy.js';

export type BrowserOpenRefusalCode =
  | 'policy_denied'
  | 'grant_rejected'
  | 'host_unavailable'
  | 'redemption_unavailable';

export class BrowserOpenRefusalError extends Error {
  readonly code: BrowserOpenRefusalCode;

  constructor(code: BrowserOpenRefusalCode, message: string) {
    super(message);
    this.name = 'BrowserOpenRefusalError';
    this.code = code;
  }
}

/** The one-shot grant produced by the canonical P01 approval path. */
export interface TrustedBrowserOpenGrant {
  readonly grantId: string;
  readonly openId: string;
  readonly runRef: string;
  readonly workspaceRef: string;
  readonly normalizedUrl: string;
  readonly requestFingerprint: string;
  readonly p01ApprovalRef: string;
  readonly hostLeaseRef: string;
  /**
   * The canonical, agent-owned redemption this open belongs to (the durable
   * admission the one-shot is anchored to). The desktop never mints it: it is
   * carried from the authority that owns the durable store and is what the
   * redemption port redeems against.
   */
  readonly redemptionRef: string;
  readonly issuedAtIso: string;
  readonly expiresAtIso: string;
}

const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$/;

function assertSafeRef(value: unknown, field: string): string {
  if (typeof value !== 'string' || !SAFE_REF.test(value.trim())) {
    throw new BrowserOpenContractError(`${field} must be a bounded safe reference`);
  }
  return value.trim();
}

function assertInstant(value: unknown, field: string): string {
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) {
    throw new BrowserOpenContractError(`${field} must be an ISO instant string`);
  }
  return value.trim();
}

export function assertTrustedBrowserOpenGrant(value: unknown): TrustedBrowserOpenGrant {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new BrowserOpenContractError('trusted browser open grant must be an object');
  }
  const record = value as Record<string, unknown>;
  assertSafeRef(record.grantId, 'grantId');
  assertSafeRef(record.openId, 'openId');
  assertSafeRef(record.runRef, 'runRef');
  assertSafeRef(record.workspaceRef, 'workspaceRef');
  // A URL is not a bounded reference: it carries query/fragment material. Use the
  // shared shape rule; the host applies the public-URL policy separately.
  assertBoundedUrl(record.normalizedUrl, 'normalizedUrl');
  assertSafeRef(record.requestFingerprint, 'requestFingerprint');
  assertSafeRef(record.p01ApprovalRef, 'p01ApprovalRef');
  assertSafeRef(record.hostLeaseRef, 'hostLeaseRef');
  assertSafeRef(record.redemptionRef, 'redemptionRef');
  const issuedAtIso = assertInstant(record.issuedAtIso, 'issuedAtIso');
  const expiresAtIso = assertInstant(record.expiresAtIso, 'expiresAtIso');
  const lifetime = (Date.parse(expiresAtIso) - Date.parse(issuedAtIso)) / 1000;
  if (!(lifetime > 0) || lifetime > BROWSER_OPEN_MAX_TTL_SECONDS) {
    throw new BrowserOpenContractError(
      `browser open grant lifetime must be positive and at most ${BROWSER_OPEN_MAX_TTL_SECONDS} seconds`,
    );
  }
  return { ...(record as unknown as TrustedBrowserOpenGrant), issuedAtIso, expiresAtIso };
}

/** Outcome of one ephemeral view session, as reported by the injected port. */
export interface BrowserOpenViewSession {
  readonly navigationBlocked: boolean;
  readonly loadFailed: boolean;
  readonly finalUrl: string | null;
  readonly redirectCount: number;
  readonly dialogsSuppressed: number;
  /**
   * Destroys the ephemeral view immediately. A `loaded` view is intentionally
   * left visible for the user and is closed by the port's own lease-expiry
   * timer; every other outcome closes it here.
   */
  close(): Promise<void>;
}

export interface BrowserOpenViewPort {
  /** False when no trusted view host is wired: the host then fails closed. */
  readonly configured: boolean;
  /**
   * Lease-scoped teardown of anything this port created for `hostLeaseRef`.
   *
   * The host calls this whenever `open` never resolves or fails, so cleanup cannot
   * depend on a session that was never returned or on an unresponsive port's own
   * timers. A port that has nothing for the lease must resolve without error.
   */
  close(hostLeaseRef: string): Promise<void>;
  open(input: {
    readonly hostLeaseRef: string;
    readonly approvedUrl: string;
    readonly expiresAtIso: string;
    /** Trusted P01-approved open identity, never sourced from the renderer. */
    readonly controlCorrelation?: {
      readonly runRef: string;
      readonly workspaceRef: string;
      readonly ownerRef: string;
    };
    /**
     * Per-navigation gate. The port must call this for every navigation and
     * redirect and prevent the navigation when it returns false.
     */
    readonly onNavigationAttempt: (candidate: unknown) => boolean;
  }): Promise<BrowserOpenViewSession>;
}

/**
 * The Desktop-side binding of the canonical, agent-owned one-shot authority.
 *
 * #3611: the desktop has no durable store of its own (`DESKTOP_RUN_DATABASE=0`),
 * so it must not become a second replay authority either. `redeem` is the durable
 * gate: it is awaited exactly once per open, **before any view exists**, and its
 * refusal is the restart-safe denial. The host's own consumed set is a fast path
 * only — losing it on restart must not re-enable an open.
 */
export interface BrowserOpenRedemptionPort {
  /** False when no canonical redemption authority is wired: the host fails closed. */
  readonly configured: boolean;
  redeem(input: {
    readonly redemptionRef: string;
    readonly requestFingerprint: string;
    readonly openId: string;
    readonly runRef: string;
  }): Promise<void>;
}

/** Fails closed until a canonical redemption authority is bound. */
export function unconfiguredBrowserOpenRedemption(): BrowserOpenRedemptionPort {
  return Object.freeze({
    configured: false,
    redeem: async () => {
      throw new BrowserOpenRefusalError(
        'redemption_unavailable',
        'no canonical browser open redemption authority is configured',
      );
    },
  });
}

export interface BrowserOpenHostDependencies {
  readonly view: BrowserOpenViewPort;
  readonly redemption: BrowserOpenRedemptionPort;
  readonly now?: () => Date;
  readonly timeoutMs?: number;
}

export class BrowserOpenHost {
  readonly #view: BrowserOpenViewPort;
  readonly #redemption: BrowserOpenRedemptionPort;
  readonly #now: () => Date;
  readonly #timeoutMs: number;
  /** Fast path only. Never the replay authority. */
  readonly #consumed = new Set<string>();

  constructor(dependencies: BrowserOpenHostDependencies) {
    if (!dependencies || typeof dependencies.view !== 'object' || dependencies.view === null) {
      throw new BrowserOpenContractError('browser open host requires an injected view port');
    }
    if (
      !dependencies.redemption ||
      typeof dependencies.redemption !== 'object' ||
      dependencies.redemption === null ||
      typeof dependencies.redemption.redeem !== 'function'
    ) {
      throw new BrowserOpenContractError(
        'browser open host requires an injected canonical redemption port',
      );
    }
    this.#view = dependencies.view;
    this.#redemption = dependencies.redemption;
    this.#now = dependencies.now ?? (() => new Date());
    this.#timeoutMs = dependencies.timeoutMs ?? BROWSER_OPEN_DEFAULT_TIMEOUT_MS;
  }

  get consumedCount(): number {
    return this.#consumed.size;
  }

  /** True only when a canonical redemption authority is actually bound. */
  get redemptionConfigured(): boolean {
    return this.#redemption.configured === true;
  }

  async open(
    request: ApprovedBrowserOpenRequest,
    grant: TrustedBrowserOpenGrant,
  ): Promise<BrowserOpenReceipt> {
    const approved = assertApprovedBrowserOpenRequest(request);
    const trustedGrant = assertTrustedBrowserOpenGrant(grant);

    // The only URL the host may navigate is the canonical policy output.
    if (!isPermittedPublicUrl(approved.normalizedUrl)) {
      throw new BrowserOpenRefusalError('policy_denied', 'approved browser open URL is not permitted');
    }
    if (trustedGrant.normalizedUrl !== approved.normalizedUrl) {
      throw new BrowserOpenRefusalError(
        'grant_rejected',
        'browser open grant does not bind this approved URL',
      );
    }
    if (
      trustedGrant.openId !== approved.openId ||
      trustedGrant.runRef !== approved.runRef ||
      trustedGrant.workspaceRef !== approved.workspaceRef ||
      trustedGrant.requestFingerprint !== approved.requestFingerprint ||
      trustedGrant.hostLeaseRef !== approved.hostLeaseRef
    ) {
      throw new BrowserOpenRefusalError('grant_rejected', 'browser open grant binding mismatch');
    }
    if (Date.parse(trustedGrant.expiresAtIso) > Date.parse(approved.expiresAtIso)) {
      throw new BrowserOpenRefusalError('grant_rejected', 'grant outlives the approved request');
    }

    const startedAt = this.#now();
    if (startedAt.getTime() >= Date.parse(trustedGrant.expiresAtIso)) {
      throw new BrowserOpenRefusalError('grant_rejected', 'browser open grant has expired');
    }

    const consumptionKey = `${trustedGrant.requestFingerprint}\u0000${trustedGrant.p01ApprovalRef}`;
    if (this.#consumed.has(consumptionKey)) {
      throw new BrowserOpenRefusalError(
        'grant_rejected',
        'browser open grant has already been consumed',
      );
    }

    if (!this.#view.configured) {
      throw new BrowserOpenRefusalError('host_unavailable', 'no trusted browser view host is configured');
    }
    if (!this.redemptionConfigured) {
      throw new BrowserOpenRefusalError(
        'redemption_unavailable',
        'no canonical browser open redemption authority is configured',
      );
    }

    // The durable gate, and it runs BEFORE any view exists. A refusal here is the
    // restart-safe denial: it comes from the canonical authority, not from this
    // process's memory, so a fresh host cannot accept a replayed grant.
    await this.#redemption.redeem({
      redemptionRef: trustedGrant.redemptionRef,
      requestFingerprint: trustedGrant.requestFingerprint,
      openId: trustedGrant.openId,
      runRef: trustedGrant.runRef,
    });
    this.#consumed.add(consumptionKey);

    let session: BrowserOpenViewSession | null = null;
    let outcome: BrowserOpenLoadOutcome = 'cancelled';
    let finalUrl: string | null = null;
    let redirectCount = 0;
    let dialogsSuppressed = 0;
    try {
      session = await this.#openWithTimeout(approved, trustedGrant);
      redirectCount = session.redirectCount;
      dialogsSuppressed = session.dialogsSuppressed;
      if (session.navigationBlocked) {
        outcome = 'navigation_blocked';
        finalUrl = null;
      } else if (session.loadFailed || session.finalUrl === null) {
        outcome = 'load_failed';
        finalUrl = null;
      } else if (!isPermittedPublicUrl(session.finalUrl)) {
        outcome = 'navigation_blocked';
        finalUrl = null;
      } else if (!isNavigationPermitted(session.finalUrl, approved.normalizedUrl)) {
        outcome = 'navigation_blocked';
        finalUrl = null;
      } else {
        outcome = 'loaded';
        finalUrl = session.finalUrl;
      }
    } catch (error) {
      if (error instanceof BrowserOpenTimeoutError) outcome = 'timeout';
      else if (error instanceof BrowserOpenCancelledError) outcome = 'cancelled';
      else throw error;
    } finally {
      // A loaded view stays visible until the grant expires (port-owned timer);
      // every other outcome closes the ephemeral view immediately. When the port
      // never handed back a session, tear the view down by lease instead — an
      // orphaned view is exactly what a timeout must not leave behind.
      if (outcome !== 'loaded') {
        if (session !== null) await session.close().catch(() => undefined);
        else await this.#view.close(trustedGrant.hostLeaseRef).catch(() => undefined);
      }
    }

    const finishedAt = this.#now();
    return buildBrowserOpenReceipt({
      openId: approved.openId,
      runRef: approved.runRef,
      workspaceRef: approved.workspaceRef,
      hostLeaseRef: approved.hostLeaseRef,
      requestedUrlNormalized: approved.normalizedUrl,
      finalUrlNormalized: finalUrl,
      loadOutcome: outcome,
      redirectCount: Math.max(0, Math.min(redirectCount, BROWSER_OPEN_MAX_REDIRECTS)),
      dialogsSuppressed: Math.max(0, Math.trunc(dialogsSuppressed)),
      openedAtIso: startedAt.toISOString(),
      closedAtIso: finishedAt.toISOString(),
      elapsedMs: Math.max(0, finishedAt.getTime() - startedAt.getTime()),
      hostRef: BROWSER_OPEN_HOST_REF,
      requestFingerprint: approved.requestFingerprint,
      p01ApprovalRef: approved.p01ApprovalRef,
      evidenceRef: approved.evidenceRef,
      admissionRef: approved.admissionRef,
      revisionRef: approved.revisionRef,
      pageContentIncluded: false,
      cookieIncluded: false,
      credentialIncluded: false,
      domApiExposed: false,
      networkScope: 'approved_url_fetch_only',
    });
  }

  async #openWithTimeout(
    request: ApprovedBrowserOpenRequest,
    grant: TrustedBrowserOpenGrant,
  ): Promise<BrowserOpenViewSession> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new BrowserOpenTimeoutError()), this.#timeoutMs);
    });
    try {
      return await Promise.race([
        this.#view.open({
          hostLeaseRef: grant.hostLeaseRef,
          approvedUrl: request.normalizedUrl,
          expiresAtIso: grant.expiresAtIso,
          controlCorrelation: {
            runRef: request.runRef,
            workspaceRef: request.workspaceRef,
            ownerRef: request.ownerRef,
          },
          onNavigationAttempt: (candidate: unknown) =>
            isNavigationPermitted(candidate, request.normalizedUrl),
        }),
        timeout,
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
}

export class BrowserOpenTimeoutError extends Error {
  constructor() {
    super('browser open timed out');
    this.name = 'BrowserOpenTimeoutError';
  }
}

export class BrowserOpenCancelledError extends Error {
  constructor() {
    super('browser open was cancelled');
    this.name = 'BrowserOpenCancelledError';
  }
}

export const BROWSER_OPEN_IMPLEMENTED = true;
export const BROWSER_CONTROL_IMPLEMENTED = false;
export const PERSISTENT_BROWSER_PROFILE_SUPPORTED = false;
export const BROWSER_OPEN_PAGE_DERIVED_OUTPUT_SUPPORTED = false;
export const BROWSER_OPEN_USES_EXISTING_P01 = true;
export const SECOND_BROWSER_AUTHORITY = false;
export const BROWSER_OPEN_REDEMPTION_REQUIRED = true;
export const DESKTOP_DURABLE_REDEMPTION_AUTHORITY = false;
export const IN_PROCESS_CONSUMED_SET_IS_AUTHORITY = false;
