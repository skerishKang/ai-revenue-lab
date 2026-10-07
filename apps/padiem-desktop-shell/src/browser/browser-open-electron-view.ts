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
import type { BrowserOpenViewPort, BrowserOpenViewSession } from './browser-open-host.js';

export const BROWSER_OPEN_VIEW_KIND = 'desktop-trusted-main-ephemeral-view';

function ephemeralPartitionName(): string {
  // A partition name must never be persistent: an in-memory name keeps cookies,
  // cache and storage out of the user's real profile and out of disk.
  return `browser-open-${randomUUID()}`;
}

export function createElectronBrowserOpenViewPort(): BrowserOpenViewPort {
  // Lease-scoped registry. `close(hostLeaseRef)` is how the host destroys a view
  // whose `open` never resolved, so teardown does not depend on this binding's
  // lease timer firing.
  const views = new Map<string, BrowserWindow>();

  const destroy = (hostLeaseRef: string): void => {
    const window = views.get(hostLeaseRef);
    if (window === undefined) return;
    views.delete(hostLeaseRef);
    if (!window.isDestroyed()) window.destroy();
  };

  return {
    configured: true,
    async close(hostLeaseRef: string): Promise<void> {
      destroy(hostLeaseRef);
    },
    async open(input): Promise<BrowserOpenViewSession> {
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

      views.set(input.hostLeaseRef, window);

      const close = async (): Promise<void> => {
        destroy(input.hostLeaseRef);
      };

      const expiryTimer = setTimeout(() => {
        destroy(input.hostLeaseRef);
      }, Math.max(0, expiresAtMs - Date.now()));
      if (typeof expiryTimer.unref === 'function') expiryTimer.unref();

      try {
        await window.loadURL(input.approvedUrl);
      } catch {
        loadFailed = !navigationBlocked;
      } finally {
        clearTimeout(expiryTimer);
      }

      const currentUrl = window.isDestroyed() ? '' : window.webContents.getURL();
      const finalUrl = navigationBlocked || loadFailed || currentUrl === '' ? null : currentUrl;

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
}

/**
 * A `loaded` view is left visible for the user and is destroyed by the
 * lease-expiry timer above; the host closes every other outcome immediately.
 */
export const BROWSER_OPEN_VIEW_LIFETIME = 'grant-bounded';
export const BROWSER_OPEN_VIEW_VISIBLE_TO_USER = true;
export const BROWSER_OPEN_VIEW_DEVTOOLS = false;
export const BROWSER_OPEN_VIEW_PAGE_DERIVED_OUTPUT = false;
