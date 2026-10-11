/**
 * CLAW2 #3093 — single-instance ownership and second-instance forwarding.
 *
 * On Windows, a `padiem://` handoff that arrives while the shell is already
 * running is delivered by launching a **second instance** whose argv contains
 * the deep link. The first instance must own the scheme, detect the second
 * launch, extract the bounded `padiem://` argument, and forward it to the
 * *existing* intake — never re-parse its meaning here.
 *
 *   SINGLE_INSTANCE_OWNER=YES            (exactly one shell process per machine user)
 *   SECOND_DEEPLINK_PARSER_AUTHORITY=0   (extraction only; the #3083 bounded
 *                                         parser + controller seam remain the
 *                                         sole interpretation authority)
 *
 * Extraction rules are deliberately dumb and safe:
 *   - only entries that start with `padiem://` (case-insensitive scheme, like
 *     the existing #3083 argv intake) are considered;
 *   - the first such entry wins; a second-instance launch carrying multiple
 *     deep links is malformed input, not a queue;
 *   - nothing is trimmed, joined, decoded, or normalized here — the raw
 *     candidate goes to the same bounded parser the first-launch argv intake
 *     already uses, so length/control-character/param limits apply unchanged.
 */

import { PAIRING_SEAM } from '../contract/pairing-deeplink.js';

const SCHEME_PREFIX = `${PAIRING_SEAM.SCHEME}://`.toLowerCase();

/** Minimal surface of `Electron.App` this module needs; injected for tests. */
export interface SingleInstanceApp {
  requestSingleInstanceLock(): boolean;
  /** Electron's real shape: `(event, argv, workingDirectory)`. */
  on(
    event: 'second-instance',
    listener: (event: unknown, argv: readonly string[], workingDirectory?: string) => void,
  ): void;
}

/** Extract the first bounded `padiem://` candidate from a second-instance argv. */
export function extractDeepLinkArgv(argv: readonly string[]): string | null {
  for (const entry of argv) {
    if (typeof entry !== 'string') {
      continue;
    }
    if (entry.toLowerCase().startsWith(SCHEME_PREFIX)) {
      return entry;
    }
  }
  return null;
}

export interface SingleInstanceForwardingOptions {
  readonly app: SingleInstanceApp;
  /** Same intake the first-launch argv path uses (controller.pairingDeepLinkSubmit). */
  readonly forwardDeepLink: (deepLink: string) => void;
  /** Called when this process failed to acquire the lock and must quit. */
  readonly onNotOwner: () => void;
  /**
   * Called for any second-instance launch, deep link present or not, so the
   * owner can bring its window to the foreground. A bare re-launch of the
   * shortcut must wake the app, not silently do nothing.
   */
  readonly onSecondInstance?: () => void;
}

export interface SingleInstanceOutcome {
  readonly owner: boolean;
}

/**
 * Acquire the single-instance lock. The owner registers the forwarding hook;
 * a non-owner is told to quit immediately, before any window or runner exists.
 */
export function acquireSingleInstanceOwnership(options: SingleInstanceForwardingOptions): SingleInstanceOutcome {
  const owner = options.app.requestSingleInstanceLock();
  if (!owner) {
    options.onNotOwner();
    return { owner: false };
  }
  options.app.on('second-instance', (_event, argv) => {
    const candidate = extractDeepLinkArgv(argv);
    if (candidate !== null) {
      options.forwardDeepLink(candidate);
    }
    // A second-instance launch without any padiem:// argument (e.g. the user
    // double-clicked the shortcut again) must still wake the primary window;
    // that is the Electron main's concern, wired via onSecondInstance below.
    options.onSecondInstance?.();
  });
  return { owner: true };
}
