/**
 * CLAW2 #3093 — Windows `padiem://` protocol registration.
 *
 * The shell must be reachable from a real Windows protocol handoff. This
 * module decides *how* the protocol client is registered for the current
 * launch shape and nothing else:
 *
 *   - a packaged build registers the scheme directly; the NSIS installer also
 *     declares it through `protocols:` in `electron-builder.yml`, so a fresh
 *     install is reachable before the app ever runs;
 *   - a dev launch (`process.defaultApp` — Electron started as
 *     `electron <app-dir>`) must register the Electron binary *with the app
 *     directory as an argument*, otherwise Windows would launch bare Electron
 *     with no application;
 *   - non-Windows platforms register nothing. The scheme contract is a
 *     Windows handoff contract; silently "succeeding" elsewhere would fake
 *     capability the acceptance evidence is about.
 *
 * Authority boundary (unchanged from #3083):
 *   PAIRING_AUTHORITY_IMPLEMENTED=NO
 *   SESSION_MINT_IMPLEMENTED=NO
 *   CREDENTIAL_PERSISTENCE=NO
 *   BROKER_TRANSPORT_IMPLEMENTED=NO
 *
 * Registration only makes the shell *reachable*. What a delivered deep link
 * means remains owned by the existing bounded parser seam and #3080.
 */

import { PAIRING_SEAM } from '../contract/pairing-deeplink.js';

export const PROTOCOL_SCHEME = PAIRING_SEAM.SCHEME;

/** Minimal surface of `Electron.App` this module needs; injected for tests. */
export interface ProtocolClientApp {
  setAsDefaultProtocolClient(
    scheme: string,
    path?: string,
    args?: readonly string[],
  ): boolean;
}

export interface ProtocolRegistrationInput {
  readonly platform: NodeJS.Platform;
  readonly packaged: boolean;
  /** `process.defaultApp` — truthy when launched as `electron <app-dir>`. */
  readonly defaultApp: boolean;
  /** `process.execPath` — the running binary (Electron or packaged shell). */
  readonly execPath: string;
  /** `app.getAppPath()` — the app directory for dev launches. */
  readonly appPath: string;
}

export interface ProtocolRegistrationPlan {
  readonly action: 'register-direct' | 'register-dev-host' | 'skip-not-windows' | 'skip-dev-without-app-path';
  readonly scheme: string;
  readonly hostPath: string | null;
  readonly hostArgs: readonly string[] | null;
  readonly reason: string;
}

/**
 * Pure decision function. Returns what registration *means* for this launch
 * shape; `registerWindowsProtocolClient` performs it. Kept separate so the
 * dev-mode `process.defaultApp` requirement is testable without Electron.
 */
export function windowsProtocolRegistrationPlan(input: ProtocolRegistrationInput): ProtocolRegistrationPlan {
  if (input.platform !== 'win32') {
    return {
      action: 'skip-not-windows',
      scheme: PROTOCOL_SCHEME,
      hostPath: null,
      hostArgs: null,
      reason: `protocol registration is a Windows handoff contract; ${input.platform} registers nothing`,
    };
  }
  if (!input.packaged && input.defaultApp) {
    if (input.appPath.length === 0) {
      return {
        action: 'skip-dev-without-app-path',
        scheme: PROTOCOL_SCHEME,
        hostPath: null,
        hostArgs: null,
        reason: 'dev launch must name the app directory; refusing a bare-Electron registration',
      };
    }
    return {
      action: 'register-dev-host',
      scheme: PROTOCOL_SCHEME,
      hostPath: input.execPath,
      hostArgs: [input.appPath],
      reason: 'dev launch registers the Electron binary with the app directory argument',
    };
  }
  return {
    action: 'register-direct',
    scheme: PROTOCOL_SCHEME,
    hostPath: null,
    hostArgs: null,
    reason: 'packaged build registers the scheme against the shell binary',
  };
}

export interface ProtocolRegistrationResult {
  readonly registered: boolean;
  readonly plan: ProtocolRegistrationPlan;
}

export function registerWindowsProtocolClient(
  app: ProtocolClientApp,
  input: ProtocolRegistrationInput,
): ProtocolRegistrationResult {
  const plan = windowsProtocolRegistrationPlan(input);
  if (plan.action !== 'register-direct' && plan.action !== 'register-dev-host') {
    return { registered: false, plan };
  }
  const ok =
    plan.action === 'register-dev-host'
      ? app.setAsDefaultProtocolClient(plan.scheme, plan.hostPath ?? undefined, [...(plan.hostArgs ?? [])])
      : app.setAsDefaultProtocolClient(plan.scheme);
  return { registered: ok, plan };
}

export const PROTOCOL_REGISTRATION_CONTRACT = Object.freeze({
  SCHEME: PROTOCOL_SCHEME,
  AUTHORITY_OWNER: '#3093',
  REGISTERS_ON_NON_WINDOWS: false,
  DEV_MODE_REQUIRES_APP_PATH: true,
  PARSES_DEEP_LINKS: false,
  PAIRING_AUTHORITY_IMPLEMENTED: false,
} as const);
