/**
 * #3669 / #3583 — source-only trusted-main browser-control product bridge.
 *
 * Connects the exact live ephemeral BrowserOpen view to the #3629 observation
 * source, #3647 bounded Input.* host and canonical #3669 resident P01 lease.
 * This module has NO renderer/IPC entry point and never constructs an approval.
 * Only a trusted-main caller holding a separately approved context can bind.
 */
import { composeTrustedBrowserActions } from './browser-action-composition.js';
import { createElectronBrowserActionBinding, type ActionWebContentsLike } from './browser-action-electron-binding.js';
import { composeTrustedBrowserObservation } from './browser-observation-composition.js';
import {
  boundedOriginFromUrl,
  createElectronBrowserObservationSource,
  type ObservationWebContentsLike,
} from './browser-observation-electron-source.js';
import type { BoundedBrowserActionRequest, BoundedActionReceipt } from './browser-action-contract.js';
import {
  createResidentBrowserControlLeaseAuthority,
  validateBrowserControlLeaseContext,
  type BrowserControlLeaseContext,
  type ResidentBrowserControlLeaseBoundary,
} from '../conversation/resident-browser-control-lease.js';

export interface TrustedControlView {
  readonly webContents: ActionWebContentsLike & ObservationWebContentsLike;
  readonly runRef: string;
  readonly workspaceRef: string;
  readonly ownerRef: string;
}

export interface TrustedMainBrowserActionInput {
  readonly findActiveControlView: (hostLeaseRef: string) => TrustedControlView | null;
  readonly residentBoundary: ResidentBrowserControlLeaseBoundary;
}

export interface BoundTrustedBrowserControl {
  readonly configured: true;
  execute(request: BoundedBrowserActionRequest): Promise<BoundedActionReceipt>;
  close(): Promise<void>;
}

function deny(reason: string): Error {
  return Object.assign(new Error(reason), { code: 'host_unavailable' });
}

/**
 * A live view is identified by the HOST-OWNED browser.open lease reference.
 * Matching run/workspace/owner and public bare origin are required BEFORE
 * constructing observation, Input.* binding or a resident lease port.
 * P01 remains the single admission authority on every execute.
 */
export function createTrustedMainBrowserActionOwner(input: TrustedMainBrowserActionInput): {
  readonly bindApprovedView: (hostLeaseRef: string, context: BrowserControlLeaseContext) => BoundTrustedBrowserControl;
} {
  return Object.freeze({
    bindApprovedView(hostLeaseRef: string, context: BrowserControlLeaseContext): BoundTrustedBrowserControl {
      validateBrowserControlLeaseContext(context);
      const view = input.findActiveControlView(hostLeaseRef);
      if (view === null) throw deny('no live canonical browser.open view for this lease');
      if (view.runRef !== context.runRef || view.workspaceRef !== context.workspaceRef ||
          view.ownerRef !== context.ownerRef) {
        throw deny('the canonical browser session identity does not match the live open view');
      }
      if (boundedOriginFromUrl(view.webContents.getURL()) !== context.originScope) {
        throw deny('the live view is outside the canonical P01 origin scope');
      }

      const source = createElectronBrowserObservationSource(view.webContents);
      const observation = composeTrustedBrowserObservation({ source });
      const binding = createElectronBrowserActionBinding(view.webContents);
      const authority = createResidentBrowserControlLeaseAuthority({
        context,
        boundary: input.residentBoundary,
      });
      const composed = composeTrustedBrowserActions({
        observation: observation.host,
        binding,
        leaseAuthority: authority,
      });
      let closed = false;
      return Object.freeze({
        configured: true as const,
        async execute(request: BoundedBrowserActionRequest): Promise<BoundedActionReceipt> {
          if (closed) throw deny('trusted browser control handle has closed');
          const current = input.findActiveControlView(hostLeaseRef);
          // Reject a destroyed/replaced view even if the lease budget remains.
          if (!current || current.webContents !== view.webContents ||
              current.runRef !== context.runRef ||
              current.workspaceRef !== context.workspaceRef ||
              current.ownerRef !== context.ownerRef) {
            throw deny('canonical browser view expired, closed or changed');
          }
          // The real action host makes a FRESH observation and re-checks P01.
          return composed.host.execute(request);
        },
        async close(): Promise<void> {
          if (closed) return;
          closed = true;
          await source.close();
          await binding.close();
        },
      });
    },
  });
}

export const TRUSTED_MAIN_RESIDENT_BROWSER_CONTROL_BRIDGE = true;
export const RENDERER_BROWSER_CONTROL_IPC_ADDED = false;
export const SECOND_BROWSER_APPROVAL_AUTHORITY = false;
export const TRUSTED_VIEW_BINDING_REQUIRES_P01_CONTEXT = true;
