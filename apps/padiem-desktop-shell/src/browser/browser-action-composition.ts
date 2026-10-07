/**
 * #3647 / #3669 — trusted-main bounded action composition root.
 *
 * Wires exactly three injected ports:
 *
 *   observation     the #3629 trusted observation host (fresh projection per
 *                   action),
 *   binding         the input-synthesis binding (in the product,
 *                   `createElectronBrowserActionBinding(<webContents>)`), and
 *   leaseAuthority  the canonical two-phase lease admission port (#3669
 *                   DECISION=B). The real implementation is
 *                   `createResidentBrowserControlLeaseAuthority` in
 *                   `conversation/resident-browser-control-lease.ts`, which
 *                   speaks the two bounded request kinds to the supervised
 *                   resident; trusted view wiring is the follow-up child. No
 *                   second approval store exists and none is created here.
 *
 *   no Electron import — the composition is hermetic and unit-testable;
 *   every default fails closed, so an unwired build refuses every action;
 *   no IPC surface, no renderer entry point exists.
 */

import {
  BrowserActionHost,
  type BrowserActionDispatchPort,
  type BrowserActionLeaseAuthority,
} from './browser-action-host.js';
import type { BrowserObservationHost } from './browser-observation-host.js';

/** Fails closed until a trusted input-synthesis binding is injected. */
export function unconfiguredActionDispatchBinding(): BrowserActionDispatchPort {
  return Object.freeze({
    configured: false,
    dispatch: async () => {
      throw new Error('no trusted browser action binding is configured');
    },
    close: async () => undefined,
  });
}

/** Fails closed until the canonical two-phase lease authority is injected. */
export function unconfiguredActionLeaseAuthority(): BrowserActionLeaseAuthority {
  return Object.freeze({
    configured: false,
    resolve: async () => {
      throw new Error('no canonical browser action lease authority is configured');
    },
    consume: async () => {
      throw new Error('no canonical browser action lease authority is configured');
    },
  });
}

export interface TrustedBrowserActionCompositionInput {
  /** The #3629 trusted observation host: every action binds to a fresh projection. */
  readonly observation: BrowserObservationHost;
  readonly binding?: BrowserActionDispatchPort;
  readonly leaseAuthority?: BrowserActionLeaseAuthority;
  readonly now?: () => Date;
}

export interface TrustedBrowserActionComposition {
  readonly host: BrowserActionHost;
  readonly bindingConfigured: boolean;
  readonly leaseAuthorityConfigured: boolean;
}

export function composeTrustedBrowserActions(
  input: TrustedBrowserActionCompositionInput,
): TrustedBrowserActionComposition {
  const binding = input.binding ?? unconfiguredActionDispatchBinding();
  const leaseAuthority = input.leaseAuthority ?? unconfiguredActionLeaseAuthority();
  const host = new BrowserActionHost({
    observation: input.observation,
    binding,
    leaseAuthority,
    ...(input.now === undefined ? {} : { now: input.now }),
  });
  return Object.freeze({
    host,
    bindingConfigured: binding.configured === true,
    leaseAuthorityConfigured: leaseAuthority.configured === true,
  });
}

export const TRUSTED_MAIN_BROWSER_ACTIONS_COMPOSED = true;
export const BROWSER_ACTION_ELECTRON_IMPORTED_HERE = false;
export const STEP_UP_EXECUTION_IMPLEMENTED = false;
export const GENERIC_IPC_SURFACE = false;
export const SECOND_BROWSER_AUTHORITY = false;
export const NEW_APPROVAL_STORE = false;
export const UNCONFIGURED_PORTS_FAIL_CLOSED = true;
