/**
 * #3647 — trusted input-synthesis binding for bounded browser actions.
 *
 * Implements `BrowserActionDispatchPort` against a trusted-main Electron
 * `webContents` handle injected by the product composition. Like the #3629
 * extraction source, the handle is structural: this module never imports
 * Electron itself.
 *
 * Execution is Chromium input synthesis over CDP — the exact-command allowlist
 * below is the whole surface:
 *
 *   Input.dispatchMouseEvent   click presses, wheel scrolls
 *   Input.insertText           non-sensitive typing (input synthesis, not keys)
 *   Input.dispatchKeyEvent     bounded keyboard selection (ArrowDown/Enter)
 *
 *   JAVASCRIPT_EVALUATE   never (no Runtime.* / script evaluation exists here)
 *   RAW_DOM               never (no DOM.* commands, no node handles)
 *   SCREENSHOT / PDF      never (no capture or export path exists)
 *   COOKIES / STORAGE     never (no cookies or storage access exists)
 *
 * The debugger session is attached per dispatch batch and always detached;
 * a second concurrent batch refuses instead of queueing.
 */

import type { ActionDispatchOp } from './browser-action-host.js';

export const BROWSER_ACTION_BINDING_KIND = 'desktop-trusted-main-input-synthesis@1';

export interface ActionWebContentsLike {
  debugger: {
    attach(): void;
    detach(): void;
    sendCommand(method: string, params?: unknown): Promise<unknown>;
  };
}

/** The complete CDP command allowlist of this binding. */
const ALLOWED_COMMANDS = Object.freeze([
  'Input.dispatchMouseEvent',
  'Input.insertText',
  'Input.dispatchKeyEvent',
] as const);

const KEY_CODES = Object.freeze({ ArrowDown: 40, Enter: 13 } as const);

export function createElectronBrowserActionBinding(
  webContents: ActionWebContentsLike,
): import('./browser-action-host.js').BrowserActionDispatchPort {
  let attached = false;
  let closed = false;

  const sendAllowed = async (method: string, params: Record<string, unknown>): Promise<void> => {
    if (!(ALLOWED_COMMANDS as readonly string[]).includes(method)) {
      throw new Error('debugger command outside the action-binding allowlist');
    }
    await webContents.debugger.sendCommand(method, params);
  };

  const runOp = async (op: ActionDispatchOp): Promise<void> => {
    switch (op.kind) {
      case 'click':
        await sendAllowed('Input.dispatchMouseEvent', {
          type: 'mousePressed',
          x: op.x,
          y: op.y,
          button: 'left',
          clickCount: 1,
        });
        await sendAllowed('Input.dispatchMouseEvent', {
          type: 'mouseReleased',
          x: op.x,
          y: op.y,
          button: 'left',
          clickCount: 1,
        });
        return;
      case 'wheel':
        await sendAllowed('Input.dispatchMouseEvent', {
          type: 'mouseWheel',
          x: op.x,
          y: op.y,
          deltaX: op.dx,
          deltaY: op.dy,
        });
        return;
      case 'insertText':
        await sendAllowed('Input.insertText', { text: op.text });
        return;
      case 'key':
        await sendAllowed('Input.dispatchKeyEvent', {
          type: 'rawKeyDown',
          key: op.key,
          windowsVirtualKeyCode: KEY_CODES[op.key],
        });
        await sendAllowed('Input.dispatchKeyEvent', {
          type: 'keyUp',
          key: op.key,
          windowsVirtualKeyCode: KEY_CODES[op.key],
        });
        return;
      default:
        // An op outside the bounded action vocabulary must never reach the
        // debugger session as a silent no-op.
        throw new Error('dispatch op outside the bounded action vocabulary');
    }
  };

  return {
    configured: true,
    async dispatch(ops: readonly ActionDispatchOp[]): Promise<void> {
      if (closed) throw new Error('action binding is closed');
      if (attached) throw new Error('a dispatch batch is already in progress');
      try {
        webContents.debugger.attach();
        attached = true;
        for (const op of ops) {
          await runOp(op);
        }
      } finally {
        if (attached) {
          webContents.debugger.detach();
          attached = false;
        }
      }
    },
    async close(): Promise<void> {
      closed = true;
      if (attached) {
        try {
          webContents.debugger.detach();
        } finally {
          attached = false;
        }
      }
    },
  };
}

export const BROWSER_ACTION_INPUT_SYNTHESIS_ONLY = true;
export const BROWSER_ACTION_SCRIPT_EVALUATION_NEVER = true;
