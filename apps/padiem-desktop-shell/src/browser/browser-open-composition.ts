/**
 * #3611 — trusted-main `browser.open` composition root.
 *
 * This is the single place where the approved open-only slice is assembled in the
 * Desktop trusted main process. It wires exactly two injected ports together:
 *
 *   view        the ephemeral view owner (in the product,
 *               `createElectronBrowserOpenViewPort()`), and
 *   redemption  the canonical, agent-owned one-shot authority.
 *
 * Deliberate properties:
 *
 *   * no Electron import — the composition is hermetic and unit-testable, and the
 *     only Electron-touching module stays `browser-open-electron-view.ts`;
 *   * both defaults fail closed, so an unwired build refuses instead of opening;
 *   * the desktop stays **stateless** about replay. It has no durable store
 *     (`DESKTOP_RUN_DATABASE=0`) and therefore must not become a replay
 *     authority, so the redemption port carries the durable fact and the host's
 *     own consumed set is only a fast path.
 *
 *   BROWSER_OPEN_IMPLEMENTED = true
 *   BROWSER_CONTROL_IMPLEMENTED = false
 *   SECOND_BROWSER_AUTHORITY = false
 *   DESKTOP_DURABLE_REDEMPTION_AUTHORITY = false
 */

import {
  BrowserOpenHost,
  unconfiguredBrowserOpenRedemption,
  type BrowserOpenRedemptionPort,
  type BrowserOpenViewPort,
} from './browser-open-host.js';

/** Fails closed until a trusted ephemeral view owner is injected. */
export function unconfiguredBrowserOpenViewPort(): BrowserOpenViewPort {
  return Object.freeze({
    configured: false,
    close: async () => undefined,
    open: async () => {
      throw new Error('no trusted browser open view host is configured');
    },
  });
}

export interface TrustedBrowserOpenCompositionInput {
  readonly view?: BrowserOpenViewPort;
  readonly redemption?: BrowserOpenRedemptionPort;
  readonly now?: () => Date;
  readonly timeoutMs?: number;
}

export interface TrustedBrowserOpenComposition {
  readonly host: BrowserOpenHost;
  readonly viewConfigured: boolean;
  readonly redemptionConfigured: boolean;
}

/**
 * Assemble the trusted-main host. Both ports default to fail-closed stand-ins, so
 * forgetting to wire one is a refusal and never a permissive open.
 */
export function composeTrustedBrowserOpen(
  input: TrustedBrowserOpenCompositionInput = {},
): TrustedBrowserOpenComposition {
  const view = input.view ?? unconfiguredBrowserOpenViewPort();
  const redemption = input.redemption ?? unconfiguredBrowserOpenRedemption();
  const host = new BrowserOpenHost({
    view,
    redemption,
    ...(input.now === undefined ? {} : { now: input.now }),
    ...(input.timeoutMs === undefined ? {} : { timeoutMs: input.timeoutMs }),
  });
  return Object.freeze({
    host,
    viewConfigured: view.configured === true,
    redemptionConfigured: host.redemptionConfigured,
  });
}

export const TRUSTED_MAIN_BROWSER_OPEN_COMPOSED = true;
export const BROWSER_OPEN_ELECTRON_IMPORTED_HERE = false;
export const BROWSER_CONTROL_IMPLEMENTED = false;
export const SECOND_BROWSER_AUTHORITY = false;
export const DESKTOP_DURABLE_REDEMPTION_AUTHORITY = false;
export const UNCONFIGURED_PORT_FAILS_CLOSED = true;
