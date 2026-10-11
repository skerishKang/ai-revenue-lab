/**
 * #3629 — trusted-main bounded observation composition root.
 *
 * Wires exactly one injected port:
 *
 *   source  the trusted extraction source (in the product,
 *           `createElectronBrowserObservationSource(<webContents>)` — wired by
 *           the future lease/action child, because this slice exposes no
 *           consumer channel and no generic IPC).
 *
 * Deliberate properties, mirroring the #3611 composition:
 *
 *   * no Electron import — the composition is hermetic and unit-testable;
 *   * the default source fails closed, so an unwired build refuses instead of
 *     observing;
 *   * no IPC surface, no renderer entry point, no action execution exists.
 */

import {
  BrowserObservationHost,
  type BrowserObservationSourcePort,
} from './browser-observation-host.js';

/** Fails closed until a trusted extraction source is injected. */
export function unconfiguredObservationSource(): BrowserObservationSourcePort {
  return Object.freeze({
    configured: false,
    snapshot: async () => {
      throw new Error('no trusted browser observation source is configured');
    },
    close: async () => undefined,
  });
}

export interface TrustedBrowserObservationCompositionInput {
  readonly source?: BrowserObservationSourcePort;
}

export interface TrustedBrowserObservationComposition {
  readonly host: BrowserObservationHost;
  readonly sourceConfigured: boolean;
}

export function composeTrustedBrowserObservation(
  input: TrustedBrowserObservationCompositionInput = {},
): TrustedBrowserObservationComposition {
  const source = input.source ?? unconfiguredObservationSource();
  const host = new BrowserObservationHost({ source });
  return Object.freeze({
    host,
    sourceConfigured: source.configured === true,
  });
}

export const TRUSTED_MAIN_BROWSER_OBSERVATION_COMPOSED = true;
export const BROWSER_OBSERVATION_ELECTRON_IMPORTED_HERE = false;
export const BROWSER_ACTION_EXECUTION_IMPLEMENTED = false;
export const GENERIC_IPC_SURFACE = false;
export const SECOND_BROWSER_AUTHORITY = false;
export const UNCONFIGURED_SOURCE_FAILS_CLOSED = true;
