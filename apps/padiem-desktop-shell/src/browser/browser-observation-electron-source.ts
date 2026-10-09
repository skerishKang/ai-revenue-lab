/**
 * #3629 — the trusted extraction source for bounded page observation.
 *
 * This module implements `BrowserObservationSourcePort` against a trusted-main
 * Electron `webContents` handle injected by the product composition (next
 * slice). It never imports Electron itself: the handle is structural, so the
 * extraction mapping stays hermetic and unit-testable.
 *
 * Extraction is the Chromium accessibility tree plus geometry-only CDP lookup.
 * Real Chromium AX nodes do NOT carry bounds; `DOM.getBoxModel` is allowed
 * ONLY for an AX node's numeric backendDOMNodeId to obtain a bounded quad.
 * Never request node descriptions/HTML/attributes/text. Deliberate properties:
 *
 *   JAVASCRIPT_EVALUATE      never (no script-evaluation primitive exists here)
 *   RAW_DOM                  never (only DOM.getBoxModel geometry, no DOM content)
 *   SCREENSHOT / PDF         never (no page-capture or page-export path exists)
 *   COOKIES / STORAGE        never (no cookies / storage access exists)
 *   FORM / PASSWORD VALUES   never (`value` is never read — see the mapping)
 *
 * The mapping is the boundary where raw material dies: every AX node is reduced
 * to the six bounded source fields (role, accessible name, bounds, allowlisted
 * state flags, derived interaction flags, credential marker). `node.value` —
 * which for password/text fields carries the typed secret — is never touched,
 * and only `Accessibility.*` commands are ever sent to the debugger session.
 */

import {
  BROWSER_OBSERVATION_INTERACTION_FLAG_ALLOWLIST,
  type ObservationSourceElement,
  type ObservationSourceSnapshot,
} from './browser-observation-contract.js';
import type { BrowserObservationSourcePort } from './browser-observation-host.js';

export const BROWSER_OBSERVATION_SOURCE_KIND = 'desktop-trusted-main-accessibility-tree@1';

/** Structural subset of Electron WebContents the source is allowed to touch. */
export interface ObservationWebContentsLike {
  getURL(): string;
  debugger: {
    attach(): void;
    detach(): void;
    sendCommand(method: string, params?: unknown): Promise<unknown>;
  };
}

interface CdpAxValue {
  readonly type?: string;
  readonly value?: unknown;
  readonly computedString?: string;
}

interface CdpAxProperty {
  readonly name?: string;
  readonly value?: CdpAxValue;
}

interface CdpAxNode {
  readonly nodeId?: string;
  readonly backendDOMNodeId?: number;
  readonly ignored?: boolean;
  readonly role?: CdpAxValue;
  readonly name?: CdpAxValue;
  readonly bounds?: { readonly x?: unknown; readonly y?: unknown; readonly width?: unknown; readonly height?: unknown };
  readonly checked?: string;
  readonly properties?: readonly CdpAxProperty[];
  readonly childIds?: readonly string[];
}

interface CdpAxTree {
  readonly nodes?: readonly CdpAxNode[];
}

/** Closed commands: AX metadata + box geometry only. No DOM content/JS/CDP escape. */
const ALLOWED_DEBUGGER_COMMANDS = Object.freeze(['Accessibility.getFullAXTree', 'DOM.getBoxModel'] as const);
const MAX_GEOMETRY_LOOKUPS = 64;

/** AX properties projected into bounded state flags (allowlist lives in the contract). */
const STATE_PROPERTY_FLAGS = Object.freeze({
  disabled: 'disabled',
  focused: 'focused',
  focusable: 'focusable',
  required: 'required',
  readonly: 'readonly',
  selected: 'selected',
  expanded: 'expanded',
  collapsed: 'collapsed',
  invalid: 'invalid',
  busy: 'busy',
  multiline: 'multiline',
  multiselectable: 'multiselectable',
} as const);

const CLICKABLE_ROLES = Object.freeze(
  new Set(['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'switch', 'option', 'treeitem']),
);
const TYPEABLE_ROLES = Object.freeze(
  new Set(['textbox', 'textarea', 'searchbox', 'combobox', 'spinbutton']),
);
const SELECTABLE_ROLES = Object.freeze(new Set(['option', 'tab', 'radio', 'treeitem', 'listbox']));
const TOGGLEABLE_ROLES = Object.freeze(new Set(['checkbox', 'radio', 'switch']));
const EXPANDABLE_ROLES = Object.freeze(new Set(['combobox', 'treeitem', 'button']));

function axString(value: CdpAxValue | undefined): string | null {
  if (!value || typeof value !== 'object') return null;
  if (typeof value.value === 'string') return value.value;
  if (typeof value.computedString === 'string') return value.computedString;
  return null;
}

function propertyValue(property: CdpAxProperty | undefined): unknown {
  if (!property || typeof property !== 'object') return undefined;
  const value = property.value;
  if (!value || typeof value !== 'object') return undefined;
  if (value.value === true || value.value === false) return value.value;
  if (typeof value.value === 'string') return value.value;
  if (typeof value.computedString === 'string') return value.computedString;
  return undefined;
}

function isPasswordInput(node: CdpAxNode): boolean {
  for (const property of node.properties ?? []) {
    if (property?.name === 'textInputType' && propertyValue(property) === 'password') return true;
  }
  return false;
}

/** Bounded state flags only; every unlisted property dies here. */
function mapStateFlags(node: CdpAxNode): string[] {
  const flags = new Set<string>();
  for (const property of node.properties ?? []) {
    const mapped = property?.name ? STATE_PROPERTY_FLAGS[property.name as keyof typeof STATE_PROPERTY_FLAGS] : undefined;
    if (mapped === undefined) continue;
    if (propertyValue(property) === true) flags.add(mapped);
  }
  if (node.checked === 'true') flags.add('checked');
  else if (node.checked === 'mixed') flags.add('mixed');
  return [...flags].sort();
}

function mapInteractionFlags(role: string): string[] {
  const allowed = new Set<string>(BROWSER_OBSERVATION_INTERACTION_FLAG_ALLOWLIST);
  const flags = new Set<string>();
  if (CLICKABLE_ROLES.has(role)) flags.add('clickable');
  if (TYPEABLE_ROLES.has(role)) {
    flags.add('typeable');
    flags.add('editable');
  }
  if (SELECTABLE_ROLES.has(role)) flags.add('selectable');
  if (TOGGLEABLE_ROLES.has(role)) flags.add('toggleable');
  if (EXPANDABLE_ROLES.has(role)) flags.add('expandable');
  return [...flags].filter((flag) => allowed.has(flag)).sort();
}

/**
 * Reduce one raw AX node to the bounded source shape. `node.value` is never
 * accessed; unclassifiable nodes are dropped here so the contract layer only
 * sees well-formed source elements.
 */
type SafeBox = { x: number; y: number; width: number; height: number };

/** CDP box-model border quad only; never inspect content, attributes or DOM handles. */
function geometryFromBoxModel(raw: unknown): SafeBox | null {
  if (!raw || typeof raw !== 'object') return null;
  const model = (raw as { model?: unknown }).model;
  if (!model || typeof model !== 'object') return null;
  const quad = (model as { border?: unknown }).border;
  if (!Array.isArray(quad) || quad.length !== 8) return null;
  if (!quad.every((v: unknown) => typeof v === 'number' && Number.isFinite(v))) return null;
  const x = Math.min(quad[0], quad[2], quad[4], quad[6]);
  const y = Math.min(quad[1], quad[3], quad[5], quad[7]);
  const width = Math.max(quad[0], quad[2], quad[4], quad[6]) - x;
  const height = Math.max(quad[1], quad[3], quad[5], quad[7]) - y;
  return width > 0 && height > 0 && width <= 16384 && height <= 16384
    ? { x, y, width, height }
    : null;
}

function mapAxNode(node: CdpAxNode, geometry?: { x: number; y: number; width: number; height: number }): ObservationSourceElement | null {
  if (!node || typeof node !== 'object' || node.ignored === true) return null;
  const role = axString(node.role);
  if (role === null) return null;
  const name = axString(node.name) ?? '';
  const raw = node.bounds ?? geometry;
  const bounds =
    raw && typeof raw === 'object'
      ? {
          x: typeof raw.x === 'number' ? raw.x : NaN,
          y: typeof raw.y === 'number' ? raw.y : NaN,
          width: typeof raw.width === 'number' ? raw.width : NaN,
          height: typeof raw.height === 'number' ? raw.height : NaN,
        }
      : null;
  if (bounds === null) return null;
  return {
    role,
    // The accessible name/label only. For credential controls the contract
    // masks it; the typed value is never read from the tree at all.
    name: isPasswordInput(node) ? '' : name,
    bounds,
    stateFlags: mapStateFlags(node),
    interactionFlags: mapInteractionFlags(role),
    credentialField: isPasswordInput(node),
  };
}

/** Origin-only reduction: path/query/credential material never leaves this function. */
export function boundedOriginFromUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
    if (parsed.username || parsed.password) return null;
    return parsed.origin.toLowerCase();
  } catch {
    return null;
  }
}

export function createElectronBrowserObservationSource(
  webContents: ObservationWebContentsLike,
): BrowserObservationSourcePort {
  let attached = false;
  let closed = false;

  const sendAllowed = async (method: string, params?: unknown): Promise<unknown> => {
    if (!(ALLOWED_DEBUGGER_COMMANDS as readonly string[]).includes(method)) {
      throw new Error('debugger command outside the observation allowlist');
    }
    return webContents.debugger.sendCommand(method, params);
  };

  return {
    configured: true,
    async snapshot(): Promise<ObservationSourceSnapshot> {
      if (closed) throw new Error('observation source is closed');
      if (attached) throw new Error('observation extraction is already in progress');
      const originRef = boundedOriginFromUrl(webContents.getURL());
      if (originRef === null) throw new Error('trusted view is not on a bounded http(s) origin');
      try {
        webContents.debugger.attach();
        attached = true;
        const tree = (await sendAllowed('Accessibility.getFullAXTree', {})) as CdpAxTree | null;
        const nodes = tree && typeof tree === 'object' ? (tree.nodes ?? []) : [];
        const elements: ObservationSourceElement[] = [];
        let geometryLookups = 0;
        for (const node of nodes) {
          let geometry: SafeBox | undefined;
          // Real Chromium AX tree has no pixel bounds. Ask only for the box
          // geometry of a clickable/typeable AX node (never inspect DOM text).
          const role = axString(node?.role);
          if (
            node && node.ignored !== true && node.bounds === undefined &&
            role !== null && mapInteractionFlags(role).length > 0 &&
            Number.isSafeInteger(node.backendDOMNodeId) &&
            (node.backendDOMNodeId ?? 0) > 0 &&
            geometryLookups < MAX_GEOMETRY_LOOKUPS
          ) {
            geometryLookups += 1;
            try {
              const result = await sendAllowed('DOM.getBoxModel', {
                backendNodeId: node.backendDOMNodeId,
              });
              geometry = geometryFromBoxModel(result) ?? undefined;
            } catch {
              // Detached/hidden boxes do not grant a click target.
            }
          }
          const mapped = mapAxNode(node, geometry);
          if (mapped !== null) elements.push(mapped);
        }
        return Object.freeze({ origin: originRef, elements: Object.freeze(elements) });
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

export const BROWSER_OBSERVATION_ACCESSIBILITY_EXTRACTION_ONLY = true;
export const BROWSER_OBSERVATION_RAW_VALUE_NEVER_READ = true;
