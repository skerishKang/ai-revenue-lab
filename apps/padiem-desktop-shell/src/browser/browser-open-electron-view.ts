/**
 * #3611 — the ONLY Desktop module allowed to touch Electron browser/session APIs.
 *
 * It implements `BrowserOpenViewPort` for the trusted main process:
 *
 *   EPHEMERAL_SESSION=YES            one fresh in-memory session per open (no persistent partition)
 *   EXISTING_USER_PROFILE_REUSE=NO   no profile path, no cookie import, no credential helper
 *   RENDERER_BROWSER_AUTHORITY=NO    no preload, no node integration, no exposed bridge
 *   PAGE_DERIVED_OUTPUT=0            no title/text/DOM/screenshot/PDF path exists
 *   WINDOW_OPEN=DENY / DOWNLOADS=DENY / PERMISSIONS=DENY / NAVIGATION=GATED
 *
 * Every navigation and redirect is passed back to the host's policy gate; the
 * binding never decides policy itself. Teardown closes the window, which
 * destroys the ephemeral session.
 */

import { randomUUID } from 'node:crypto';
import { BrowserWindow } from 'electron';

import { BROWSER_OPEN_MAX_REDIRECTS } from './browser-open-contracts.js';
import { isNavigationPermitted, isPermittedPublicUrl } from './public-url-policy.js';
import type { BrowserOpenViewPort, BrowserOpenViewSession } from './browser-open-host.js';
import type { TrustedControlView } from './browser-action-trusted-main.js';

export const BROWSER_OPEN_VIEW_KIND = 'desktop-trusted-main-ephemeral-view';

function ephemeralPartitionName(): string {
  // A partition name must never be persistent: an in-memory name keeps cookies,
  // cache and storage out of the user's real profile and out of disk.
  return `browser-open-${randomUUID()}`;
}

export function createElectronBrowserOpenViewOwner(): {
  readonly port: BrowserOpenViewPort;
  readonly findActiveControlView: (hostLeaseRef: string) => TrustedControlView | null;
} {
  // Lease-scoped registry. `close(hostLeaseRef)` is how the host destroys a view
  // whose `open` never resolved, so teardown does not depend on this binding's
  // lease timer firing.
  const views = new Map<string, {
    window: BrowserWindow;
    expiresAtMs: number;
    approvedUrl: string;
    ready: boolean;
    correlation: { runRef: string; workspaceRef: string; ownerRef: string } | null;
    expiryTimer: ReturnType<typeof setTimeout> | null;
  }>();

  const destroy = (hostLeaseRef: string): void => {
    const active = views.get(hostLeaseRef);
    if (active === undefined) return;
    views.delete(hostLeaseRef);
    if (active.expiryTimer !== null) clearTimeout(active.expiryTimer);
    if (!active.window.isDestroyed()) active.window.destroy();
  };

  const findActiveControlView = (hostLeaseRef: string): TrustedControlView | null => {
    const active = views.get(hostLeaseRef);
    if (!active || !active.ready || !active.correlation ||
        Date.now() >= active.expiresAtMs ||
        active.window.isDestroyed() || active.window.webContents.isDestroyed()) return null;
    // Re-check the CURRENT URL even after the open receipt: same-origin SPA
    // navigation or a trusted view redirect must not widen the approved URL.
    const currentUrl = active.window.webContents.getURL();
    if (!isPermittedPublicUrl(currentUrl) ||
        !isNavigationPermitted(currentUrl, active.approvedUrl)) return null;
    return { webContents: active.window.webContents, ...active.correlation };
  };

  const port: BrowserOpenViewPort = {
    configured: true,
    async close(hostLeaseRef: string): Promise<void> {
      destroy(hostLeaseRef);
    },
    async open(input): Promise<BrowserOpenViewSession> {
      // The hostLeaseRef is one-shot. Reusing a live key must never replace a
      // view whose timer and close callback own the previous lease.
      if (views.has(input.hostLeaseRef)) throw new Error('duplicate canonical browser open view ref');
      const window = new BrowserWindow({
        width: 1024,
        height: 720,
        show: true,
        autoHideMenuBar: true,
        title: 'Padiem',
        webPreferences: {
          sandbox: true,
          contextIsolation: true,
          nodeIntegration: false,
          webSecurity: true,
          allowRunningInsecureContent: false,
          webviewTag: false,
          devTools: false,
          spellcheck: false,
          partition: ephemeralPartitionName(),
        },
      });
      window.setMenuBarVisibility(false);

      let navigationBlocked = false;
      let redirects = 0;
      let loadFailed = false;
      const expiresAtMs = Date.parse(input.expiresAtIso);

      window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => {
        callback(false);
      });
      window.webContents.session.setPermissionCheckHandler(() => false);
      window.webContents.session.on('will-download', (event) => event.preventDefault());
      // The title is page-derived content: never stored, never surfaced.
      window.webContents.on('page-title-updated', (event) => event.preventDefault());
      window.webContents.on('will-navigate', (event, url) => {
        if (!input.onNavigationAttempt(url)) {
          event.preventDefault();
          navigationBlocked = true;
        }
      });
      window.webContents.on('will-redirect', (event, url) => {
        redirects += 1;
        if (redirects > BROWSER_OPEN_MAX_REDIRECTS || !input.onNavigationAttempt(url)) {
          event.preventDefault();
          navigationBlocked = true;
        }
      });
      window.webContents.on('did-fail-load', () => {
        loadFailed = true;
      });

      // No control access until canonical redemption, public URL policy,
      // completed navigation and the trusted open correlations all succeed.
      const active = {
        window, expiresAtMs, approvedUrl: input.approvedUrl, ready: false,
        correlation: input.controlCorrelation ?? null,
        expiryTimer: null as ReturnType<typeof setTimeout> | null,
      };
      views.set(input.hostLeaseRef, active);
      window.on('closed', () => {
        if (views.get(input.hostLeaseRef)?.window === window) destroy(input.hostLeaseRef);
      });

      const close = async (): Promise<void> => {
        destroy(input.hostLeaseRef);
      };

      const expiryTimer = setTimeout(() => {
        destroy(input.hostLeaseRef);
      }, Math.max(0, expiresAtMs - Date.now()));
      if (typeof expiryTimer.unref === 'function') expiryTimer.unref();
      active.expiryTimer = expiryTimer;

      try {
        await window.loadURL(input.approvedUrl);
      } catch {
        loadFailed = !navigationBlocked;
      }
      // Do not clear the lease timer on success: the view must be destroyed
      // at grant expiry, including after a trusted control handoff.

      const currentUrl = window.isDestroyed() ? '' : window.webContents.getURL();
      const finalUrl = navigationBlocked || loadFailed || currentUrl === '' ? null : currentUrl;
      active.ready = finalUrl !== null && !window.isDestroyed() &&
        Date.now() < expiresAtMs && isPermittedPublicUrl(finalUrl) &&
        isNavigationPermitted(finalUrl, input.approvedUrl);

      return {
        navigationBlocked,
        loadFailed,
        finalUrl,
        redirectCount: redirects,
        // Electron suppresses JavaScript dialogs without rendering them; the
        // binding exposes no dialog API and reports no page-supplied text.
        dialogsSuppressed: 0,
        close,
      };
    },
  };
  return Object.freeze({ port, findActiveControlView });
}

/** Legacy open-only factory: callers receive no trusted control-view lookup. */
export function createElectronBrowserOpenViewPort(): BrowserOpenViewPort {
  return createElectronBrowserOpenViewOwner().port;
}

/**
 * A `loaded` view is left visible for the user and is destroyed by the
 * lease-expiry timer above; the host closes every other outcome immediately.
 */
export const BROWSER_OPEN_VIEW_LIFETIME = 'grant-bounded';
export const BROWSER_OPEN_VIEW_VISIBLE_TO_USER = true;
export const BROWSER_OPEN_VIEW_DEVTOOLS = false;
export const BROWSER_OPEN_VIEW_PAGE_DERIVED_OUTPUT = false;
