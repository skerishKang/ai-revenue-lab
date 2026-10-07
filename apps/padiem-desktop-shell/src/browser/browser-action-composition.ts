/**
 * #3647 — trusted-main bounded action composition root.
 *
 * Wires exactly three injected ports:
 *
 *   observation   the #3629 trusted observation host (fresh projection per action),
 *   binding       the input-synthesis binding (in the product,
 *                 `createElectronBrowserActionBinding(<webContents>)`), and
 *   leaseProvider the canonical bounded-lease admission port — deliberately
 *                 fail-closed until the next slice wires the canonical P01 +
 *                 durable one-shot authority into it. No second approval
 *                 store exists and none is created here.
 *
 *   no Electron import — the composition is hermetic and unit-testable;
 *   every default fails closed, so an unwired build refuses every action;
 *   no IPC surface, no renderer entry point exists.
 */

import {
  BrowserActionHost,
  type BrowserActionDispatchPort,
  type BrowserActionLeaseProvider,
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

/** Fails closed until the canonical bounded-lease authority is injected. */
export function unconfiguredActionLeaseProvider(): BrowserActionLeaseProvider {
  return Object.freeze({
    configured: false,
    lease: async () => {
      throw new Error('no canonical browser action lease authority is configured');
    },
  });
}

export interface TrustedBrowserActionCompositionInput {
  /** The #3629 trusted observation host: every action binds to a fresh projection. */
  readonly observation: BrowserObservationHost;
  readonly binding?: BrowserActionDispatchPort;
  readonly leaseProvider?: BrowserActionLeaseProvider;
  readonly now?: () => Date;
}

export interface TrustedBrowserActionComposition {
  readonly host: BrowserActionHost;
  readonly bindingConfigured: boolean;
  readonly leaseProviderConfigured: boolean;
}

export function composeTrustedBrowserActions(
  input: TrustedBrowserActionCompositionInput,
): TrustedBrowserActionComposition {
  const binding = input.binding ?? unconfiguredActionDispatchBinding();
  const leaseProvider = input.leaseProvider ?? unconfiguredActionLeaseProvider();
  const host = new BrowserActionHost({
    observation: input.observation,
    binding,
    leaseProvider,
    ...(input.now === undefined ? {} : { now: input.now }),
  });
  return Object.freeze({
    host,
    bindingConfigured: binding.configured === true,
    leaseProviderConfigured: leaseProvider.configured === true,
  });
}

export const TRUSTED_MAIN_BROWSER_ACTIONS_COMPOSED = true;
export const BROWSER_ACTION_ELECTRON_IMPORTED_HERE = false;
export const STEP_UP_EXECUTION_IMPLEMENTED = false;
export const GENERIC_IPC_SURFACE = false;
export const SECOND_BROWSER_AUTHORITY = false;
export const NEW_APPROVAL_STORE = false;
export const UNCONFIGURED_PORTS_FAIL_CLOSED = true;
