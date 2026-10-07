/**
 * #3611 — `browser.open` contract shapes (open-only, page-derived bytes = 0).
 *
 * These types describe exactly one URL open. They deliberately contain no
 * browser-control surface: no tab, no element ref, no selector, no evaluate, no
 * screenshot, no cookie or profile material, and no page-derived content.
 *
 * Validation is fail-closed and *exact*: an inbound object whose key set is not
 * the declared one — in particular one that carries a page-derived field — is
 * refused rather than silently narrowed.
 *
 * Division of labour: this module validates *shape* (keys, bounded references,
 * URL syntax, lifetime). The public-URL *policy* decision belongs to the trusted
 * host, which must refuse a non-public URL with `policy_denied` before any view
 * exists; keeping it there is what makes the refusal a bounded, projectable
 * outcome instead of a contract error.
 */

import { MAX_PUBLIC_URL_CHARS } from './public-url-policy.js';

export const BROWSER_OPEN_HOST_REF = 'desktop-trusted-main-ephemeral-view@1';
export const BROWSER_OPEN_MAX_TTL_SECONDS = 900;
export const BROWSER_OPEN_MIN_TTL_SECONDS = 60;
export const BROWSER_OPEN_MAX_REDIRECTS = 5;
export const BROWSER_OPEN_DEFAULT_TIMEOUT_MS = 30_000;

export type BrowserOpenLoadOutcome =
  | 'loaded'
  | 'navigation_blocked'
  | 'load_failed'
  | 'policy_denied'
  | 'host_unavailable'
  | 'timeout'
  | 'cancelled';

export type BrowserOpenRefusalCode = 'policy_denied' | 'grant_rejected' | 'host_unavailable';

/** Page-derived content that may never appear on this surface, in any shape. */
export const BROWSER_OPEN_FORBIDDEN_PAGE_DERIVED_KEYS = Object.freeze([
  'title',
  'pageTitle',
  'text',
  'body',
  'html',
  'source',
  'dom',
  'snapshot',
  'screenshot',
  'image',
  'pdf',
  'dialogText',
  'formValues',
  'values',
  'attributes',
  'cookies',
  'localStorage',
  'sessionStorage',
  'headers',
] as const);

/**
 * The complete approved-open request. Every field is either an opaque reference,
 * a bounded policy input, or a canonical URL the Python policy already produced.
 */
export interface ApprovedBrowserOpenRequest {
  readonly openId: string;
  readonly runRef: string;
  readonly workspaceRef: string;
  readonly ownerRef: string;
  readonly ticketRef: string;
  /** Raw URL as it appeared in the approved work ticket (correlation only). */
  readonly requestedUrl: string;
  /** Canonical policy output. This is the only URL the host may navigate. */
  readonly normalizedUrl: string;
  readonly requestFingerprint: string;
  readonly p01ApprovalRef: string;
  readonly evidenceRef: string;
  readonly admissionRef: string;
  readonly revisionRef: string;
  readonly hostLeaseRef: string;
  readonly issuedAtIso: string;
  readonly expiresAtIso: string;
}

export const APPROVED_BROWSER_OPEN_REQUEST_KEYS = Object.freeze([
  'openId',
  'runRef',
  'workspaceRef',
  'ownerRef',
  'ticketRef',
  'requestedUrl',
  'normalizedUrl',
  'requestFingerprint',
  'p01ApprovalRef',
  'evidenceRef',
  'admissionRef',
  'revisionRef',
  'hostLeaseRef',
  'issuedAtIso',
  'expiresAtIso',
] as const);

export const BROWSER_OPEN_RECEIPT_FIELDS = Object.freeze([
  'openId',
  'runRef',
  'workspaceRef',
  'hostLeaseRef',
  'requestedUrlNormalized',
  'finalUrlNormalized',
  'loadOutcome',
  'redirectCount',
  'dialogsSuppressed',
  'openedAtIso',
  'closedAtIso',
  'elapsedMs',
  'hostRef',
  'requestFingerprint',
  'p01ApprovalRef',
  'evidenceRef',
  'admissionRef',
  'revisionRef',
  'pageContentIncluded',
  'cookieIncluded',
  'credentialIncluded',
  'domApiExposed',
  'networkScope',
] as const);

/** Bounded receipt. Constructed only by the host; carries no page-derived bytes. */
export interface BrowserOpenReceipt {
  readonly openId: string;
  readonly runRef: string;
  readonly workspaceRef: string;
  readonly hostLeaseRef: string;
  readonly requestedUrlNormalized: string;
  readonly finalUrlNormalized: string | null;
  readonly loadOutcome: BrowserOpenLoadOutcome;
  readonly redirectCount: number;
  readonly dialogsSuppressed: number;
  readonly openedAtIso: string;
  readonly closedAtIso: string;
  readonly elapsedMs: number;
  readonly hostRef: string;
  readonly requestFingerprint: string;
  readonly p01ApprovalRef: string;
  readonly evidenceRef: string;
  readonly admissionRef: string;
  readonly revisionRef: string;
  readonly pageContentIncluded: false;
  readonly cookieIncluded: false;
  readonly credentialIncluded: false;
  readonly domApiExposed: false;
  readonly networkScope: 'approved_url_fetch_only';
}

export class BrowserOpenContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BrowserOpenContractError';
  }
}

const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;

function assertSafeId(value: unknown, field: string): string {
  if (typeof value !== 'string' || !SAFE_ID.test(value.trim())) {
    throw new BrowserOpenContractError(`${field} must be a bounded safe identifier`);
  }
  return value.trim();
}

function assertSafeRef(value: unknown, field: string): string {
  if (typeof value !== 'string' || !SAFE_REF.test(value.trim())) {
    throw new BrowserOpenContractError(`${field} must be a bounded safe reference`);
  }
  return value.trim();
}

/**
 * Shape-only URL check: absolute `http(s)`, bounded, control-character-free. The
 * host is the component that decides whether the URL is *permitted*.
 */
export function assertBoundedUrl(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new BrowserOpenContractError(`${field} must be a string`);
  }
  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_PUBLIC_URL_CHARS) {
    throw new BrowserOpenContractError(`${field} must be a bounded URL`);
  }
  for (const character of trimmed) {
    const code = character.codePointAt(0)!;
    if (code < 32 || code === 127) {
      throw new BrowserOpenContractError(`${field} must not contain control characters`);
    }
  }
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new BrowserOpenContractError(`${field} must be an absolute http(s) URL`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new BrowserOpenContractError(`${field} must be an absolute http(s) URL`);
  }
  if (parsed.hostname === '') {
    throw new BrowserOpenContractError(`${field} must carry a host`);
  }
  return trimmed;
}

function assertIsoInstant(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new BrowserOpenContractError(`${field} must be an ISO instant string`);
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    throw new BrowserOpenContractError(`${field} must be an ISO instant string`);
  }
  if (!/[zZ]|[+-]\d{2}:\d{2}$/.test(value.trim())) {
    throw new BrowserOpenContractError(`${field} must be timezone-aware`);
  }
  return value.trim();
}

/**
 * Fail-closed inbound validation. Any extra key — in particular any
 * page-derived key — refuses the whole request instead of being ignored.
 */
export function assertApprovedBrowserOpenRequest(value: unknown): ApprovedBrowserOpenRequest {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new BrowserOpenContractError('approved browser open request must be an object');
  }
  const record = value as Record<string, unknown>;
  const allowed = new Set<string>(APPROVED_BROWSER_OPEN_REQUEST_KEYS);
  for (const key of Object.keys(record)) {
    const lowered = key.toLowerCase();
    if (
      (BROWSER_OPEN_FORBIDDEN_PAGE_DERIVED_KEYS as readonly string[]).some(
        (forbidden) => forbidden.toLowerCase() === lowered,
      )
    ) {
      throw new BrowserOpenContractError(
        `approved browser open request must not carry page-derived field: ${key}`,
      );
    }
    if (!allowed.has(key)) {
      throw new BrowserOpenContractError(`approved browser open request has unexpected field: ${key}`);
    }
  }
  assertSafeId(record.openId, 'openId');
  assertSafeId(record.runRef, 'runRef');
  assertSafeRef(record.workspaceRef, 'workspaceRef');
  assertSafeRef(record.ownerRef, 'ownerRef');
  assertSafeRef(record.ticketRef, 'ticketRef');
  assertBoundedUrl(record.normalizedUrl, 'normalizedUrl');
  assertBoundedUrl(record.requestedUrl, 'requestedUrl');
  assertSafeRef(record.requestFingerprint, 'requestFingerprint');
  assertSafeRef(record.p01ApprovalRef, 'p01ApprovalRef');
  assertSafeRef(record.evidenceRef, 'evidenceRef');
  assertSafeRef(record.admissionRef, 'admissionRef');
  assertSafeRef(record.revisionRef, 'revisionRef');
  assertSafeRef(record.hostLeaseRef, 'hostLeaseRef');
  const issuedAtIso = assertIsoInstant(record.issuedAtIso, 'issuedAtIso');
  const expiresAtIso = assertIsoInstant(record.expiresAtIso, 'expiresAtIso');
  const lifetime = (Date.parse(expiresAtIso) - Date.parse(issuedAtIso)) / 1000;
  if (!(lifetime > 0) || lifetime > BROWSER_OPEN_MAX_TTL_SECONDS) {
    throw new BrowserOpenContractError(
      `browser open lifetime must be positive and at most ${BROWSER_OPEN_MAX_TTL_SECONDS} seconds`,
    );
  }
  return {
    ...(record as unknown as ApprovedBrowserOpenRequest),
    issuedAtIso,
    expiresAtIso,
  };
}

/** The host pins its own receipt shape so a page-derived field cannot be added. */
export function buildBrowserOpenReceipt(input: BrowserOpenReceipt): BrowserOpenReceipt {
  const produced: BrowserOpenReceipt = {
    openId: input.openId,
    runRef: input.runRef,
    workspaceRef: input.workspaceRef,
    hostLeaseRef: input.hostLeaseRef,
    requestedUrlNormalized: input.requestedUrlNormalized,
    finalUrlNormalized: input.finalUrlNormalized,
    loadOutcome: input.loadOutcome,
    redirectCount: input.redirectCount,
    dialogsSuppressed: input.dialogsSuppressed,
    openedAtIso: input.openedAtIso,
    closedAtIso: input.closedAtIso,
    elapsedMs: input.elapsedMs,
    hostRef: input.hostRef,
    requestFingerprint: input.requestFingerprint,
    p01ApprovalRef: input.p01ApprovalRef,
    evidenceRef: input.evidenceRef,
    admissionRef: input.admissionRef,
    revisionRef: input.revisionRef,
    pageContentIncluded: false,
    cookieIncluded: false,
    credentialIncluded: false,
    domApiExposed: false,
    networkScope: 'approved_url_fetch_only',
  };
  const keys = Object.keys(produced).sort();
  const declared = [...BROWSER_OPEN_RECEIPT_FIELDS].sort();
  if (keys.length !== declared.length || keys.some((key, index) => key !== declared[index])) {
    throw new BrowserOpenContractError('browser open receipt field set changed');
  }
  return Object.freeze(produced);
}
