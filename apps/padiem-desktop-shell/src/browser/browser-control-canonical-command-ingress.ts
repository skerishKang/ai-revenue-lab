/**
 * #3775 — trusted-main command entry for a future canonical browser.control
 * broker handoff. Never expose this entry to renderer/IPC: its ONLY caller
 * must be the trusted resident command consumer, not a webpage.
 *
 * This does not mint or verify a P01 approval locally. The injected `take`
 * MUST atomically redeem a broker-authorized, browser.control-specific
 * work command and return exact approved material. By default the port is
 * absent and every request refuses (no action, no new authority).
 */
import {
  validateBoundedBrowserAction,
  type BoundedActionReceipt,
  type BoundedBrowserActionRequest,
} from './browser-action-contract.js';
import type { BoundTrustedBrowserControl } from './browser-action-trusted-main.js';
import {
  validateBrowserControlLeaseContext,
  type BrowserControlLeaseContext,
} from '../conversation/resident-browser-control-lease.js';

const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/;
const APPROVED_COMMAND_KEYS = Object.freeze([
  'commandRef',
  'hostLeaseRef',
  'capability',
  'context',
  'action',
] as const);
const LEASE_CONTEXT_KEYS = Object.freeze([
  'requestFingerprint', 'browserSessionRef', 'deviceRef',
  'runRef', 'workspaceRef', 'ownerRef', 'originScope',
  'allowedActionClasses', 'ttlSeconds', 'maxActions',
] as const);
const MAX_LOCAL_COMMAND_FINGERPRINTS = 4_096;

export interface CanonicalApprovedBrowserControlCommand {
  readonly commandRef: string;
  readonly hostLeaseRef: string;
  /** This must be an independently approved action, never browser.open. */
  readonly capability: 'browser.control';
  readonly context: BrowserControlLeaseContext;
  readonly action: BoundedBrowserActionRequest;
}

/** Canonical broker-owned atomic take; no implementation or durable state in Desktop. */
export interface CanonicalBrowserControlCommandPort {
  readonly configured: boolean;
  takeApprovedCommand(commandRef: string): Promise<unknown>;
}

export interface TrustedBrowserControlOwnerPort {
  bindApprovedView(
    hostLeaseRef: string, context: BrowserControlLeaseContext,
  ): BoundTrustedBrowserControl;
}

function refuse(): Error {
  return Object.assign(
    new Error('canonical browser.control command admission unavailable or refused'),
    { code: 'host_unavailable' },
  );
}

/** Strictly validate the trusted source's bounded output, not caller-provided action bytes. */
export function validateCanonicalApprovedBrowserControlCommand(
  raw: unknown, expectedCommandRef: string,
): CanonicalApprovedBrowserControlCommand {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw refuse();
  const obj = raw as Record<string, unknown>;
  if (Object.keys(obj).length !== APPROVED_COMMAND_KEYS.length ||
      Object.keys(obj).some(k => !(APPROVED_COMMAND_KEYS as readonly string[]).includes(k))) {
    throw refuse();
  }
  if (obj['capability'] !== 'browser.control' ||
      obj['commandRef'] !== expectedCommandRef ||
      typeof obj['hostLeaseRef'] !== 'string' || !SAFE_REF.test(obj['hostLeaseRef'])) {
    throw refuse();
  }
  const context = obj['context'] as BrowserControlLeaseContext;
  let action: BoundedBrowserActionRequest;
  try {
    if (context === null || typeof context !== 'object' || Array.isArray(context) ||
        Object.keys(context).length !== LEASE_CONTEXT_KEYS.length ||
        Object.keys(context).some(k => !(LEASE_CONTEXT_KEYS as readonly string[]).includes(k))) {
      throw refuse();
    }
    validateBrowserControlLeaseContext(context);
    action = validateBoundedBrowserAction(obj['action']);
  } catch {
    throw refuse();
  }
  if (action.browserSessionRef !== context.browserSessionRef ||
      action.originRef !== context.originScope ||
      !(context.allowedActionClasses as readonly string[]).includes(action.action)) {
    throw refuse();
  }
  return Object.freeze({
    commandRef: expectedCommandRef,
    hostLeaseRef: obj['hostLeaseRef'],
    capability: 'browser.control',
    context, action,
  });
}

export function createTrustedBrowserControlCommandIngress(input: {
  readonly approvedCommands?: CanonicalBrowserControlCommandPort;
  readonly browserControl: TrustedBrowserControlOwnerPort;
}): {
  readonly configured: boolean;
  executeApprovedCommand(commandRef: string): Promise<BoundedActionReceipt>;
} {
  const port = input.approvedCommands;
  /** Fast-path duplicate barrier; only the source can enforce restart-safe CAS. */
  const seen = new Set<string>();

  return Object.freeze({
    configured: port?.configured === true,
    async executeApprovedCommand(commandRef: string): Promise<BoundedActionReceipt> {
      if (!port || port.configured !== true || typeof commandRef !== 'string' ||
          !SAFE_REF.test(commandRef) || seen.has(commandRef) ||
          seen.size >= MAX_LOCAL_COMMAND_FINGERPRINTS) throw refuse();
      seen.add(commandRef);
      let approved: CanonicalApprovedBrowserControlCommand;
      try {
        const canonical = await port.takeApprovedCommand(commandRef);
        approved = validateCanonicalApprovedBrowserControlCommand(canonical, commandRef);
      } catch {
        // No raw broker approval, command material or callback error to Desktop.
        throw refuse();
      }

      // The trusted-main view bridge rechecks the ACTUAL view identity/origin.
      // Its resident PHASE A/B then checks canonical P01 and consumes one slot
      // before Input.*. No retries, refund or fallback after taking this command.
      const bound = input.browserControl.bindApprovedView(
        approved.hostLeaseRef, approved.context,
      );
      try {
        return await bound.execute(approved.action);
      } finally {
        await bound.close();
      }
    },
  });
}

export const CANONICAL_BROWSER_CONTROL_COMMAND_SOURCE_WIRED = false;
export const TRUSTED_COMMAND_INGRESS_ADDS_RENDERER_IPC = false;
export const COMMAND_REPLAY_AUTHORITY = 'canonical-broker-only';
