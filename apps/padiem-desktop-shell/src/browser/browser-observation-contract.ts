/**
 * #3629 — bounded page-observation projection contract (owner decision #3609, D1=ENABLED_BOUNDED).
 *
 * The projection is bounded **control metadata**, never page-content retrieval.
 * Exactly one shape exists on this surface, and it is validated *exactly*: an
 * inbound element whose key set is not the declared one — in particular one that
 * carries page-derived material — is refused, never silently narrowed.
 *
 *   MAX_ELEMENTS=400  MAX_SERIALIZED_BYTES=8192  NAME_MAX_CHARS=64
 *   CREDENTIAL_FIELDS=MASKED_ONLY
 *
 * Structurally unrepresentable here (the exact-key rules below are the
 * enforcement, the forbidden list is the explicit refusal vocabulary):
 * raw DOM, raw HTML, page source, screenshots, PDF, cookies, localStorage,
 * sessionStorage, password values, form values, textarea contents, arbitrary
 * attributes, raw href/query material, JavaScript evaluation results.
 *
 * Fail-closed contract:
 *   - structural violations (forbidden/unknown keys, wrong types, invalid
 *     origin) refuse the whole projection;
 *   - an element the source could not classify (unknown role/flags, unusable
 *     geometry) is *omitted* deterministically and counted — never projected
 *     with raw fallback material;
 *   - element overflow truncates deterministically in source (document) order
 *     with a declared flag;
 *   - serialized overflow beyond the byte budget deterministically drops the
 *     lowest-priority (last) elements — also with the declared flag — and fails
 *     closed only if even an empty projection cannot fit the budget. No silent
 *     byte cutting ever happens inside an element.
 */

export const BROWSER_OBSERVATION_HOST_REF = 'desktop-trusted-main-observation@1';
export const MAX_OBSERVATION_ELEMENTS = 400;
export const MAX_SERIALIZED_OBSERVATION_BYTES = 8192;
export const MAX_ELEMENT_NAME_CHARS = 64;
export const MASKED_CREDENTIAL_NAME = '[credential]';
/** Site/origin scope and lease policy stay owned by the #3607 decision family. */
export const BROWSER_SITE_SCOPE_POLICY_OWNER = '#3607';

export type BrowserObservationErrorCode =
  | 'contract_violation'
  | 'projection_exceeds_byte_budget'
  | 'host_unavailable'
  | 'extraction_failed';

export class BrowserObservationContractError extends Error {
  readonly code: BrowserObservationErrorCode;

  constructor(code: BrowserObservationErrorCode, message: string) {
    super(message);
    this.name = 'BrowserObservationContractError';
    this.code = code;
  }
}

/** Page-derived / secret material that may never appear on this surface. */
export const BROWSER_OBSERVATION_FORBIDDEN_ELEMENT_KEYS = Object.freeze([
  'value',
  'values',
  'text',
  'content',
  'html',
  'dom',
  'source',
  'screenshot',
  'image',
  'pdf',
  'attributes',
  'href',
  'src',
  'formValues',
  'cookies',
  'localStorage',
  'sessionStorage',
] as const);

/** Keys a raw extraction source may hand to the host. `elementRef` is not one:
 * refs are derived from document order, never accepted from the source. */
export const BROWSER_OBSERVATION_SOURCE_ELEMENT_KEYS = Object.freeze([
  'role',
  'name',
  'bounds',
  'stateFlags',
  'interactionFlags',
  'credentialField',
] as const);

export const BROWSER_OBSERVATION_KEYS = Object.freeze([
  'projectionId',
  'hostRef',
  'originRef',
  'elementCount',
  'omittedElements',
  'truncated',
  'elements',
  'pageContentIncluded',
  'cookieIncluded',
  'credentialValueIncluded',
  'domApiExposed',
] as const);

/** Bounded interactive/structural roles. Anything else is unclassifiable. */
export const BROWSER_OBSERVATION_ROLE_ALLOWLIST = Object.freeze([
  'button',
  'link',
  'textbox',
  'textarea',
  'searchbox',
  'combobox',
  'checkbox',
  'radio',
  'switch',
  'slider',
  'spinbutton',
  'option',
  'tab',
  'menuitem',
  'listbox',
  'treeitem',
  'dialog',
  'alertdialog',
  'heading',
  'label',
  'statictext',
  'image',
  'list',
  'listitem',
  'table',
  'row',
  'cell',
  'group',
  'navigation',
  'main',
  'form',
  'progressbar',
  'status',
  'toolbar',
  'menubar',
] as const);

export const BROWSER_OBSERVATION_STATE_FLAG_ALLOWLIST = Object.freeze([
  'disabled',
  'focused',
  'focusable',
  'required',
  'readonly',
  'selected',
  'checked',
  'unchecked',
  'mixed',
  'expanded',
  'collapsed',
  'pressed',
  'invalid',
  'busy',
  'multiline',
  'multiselectable',
] as const);

export const BROWSER_OBSERVATION_INTERACTION_FLAG_ALLOWLIST = Object.freeze([
  'clickable',
  'typeable',
  'selectable',
  'toggleable',
  'expandable',
  'scrollable',
  'editable',
] as const);

export interface ObservationElementBounds {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface BoundedObservationElement {
  readonly elementRef: string;
  readonly role: string;
  readonly name: string;
  readonly bounds: ObservationElementBounds;
  readonly stateFlags: readonly string[];
  readonly interactionFlags: readonly string[];
  readonly credentialField: boolean;
}

export interface BoundedPageObservation {
  readonly projectionId: string;
  readonly hostRef: string;
  readonly originRef: string;
  readonly elementCount: number;
  readonly omittedElements: number;
  readonly truncated: boolean;
  readonly elements: readonly BoundedObservationElement[];
  readonly pageContentIncluded: boolean;
  readonly cookieIncluded: boolean;
  readonly credentialValueIncluded: boolean;
  readonly domApiExposed: boolean;
}

/** Raw, pre-projection material handed to the trusted host by an extraction source. */
export interface ObservationSourceElement {
  readonly role: unknown;
  readonly name: unknown;
  readonly bounds: unknown;
  readonly stateFlags: unknown;
  readonly interactionFlags: unknown;
  readonly credentialField: unknown;
}

/**
 * Stable per-snapshot element refs: derived from document order by the host,
 * never source-supplied. The same source order always yields the same refs.
 */
export function observationElementRef(sequence: number): string {
  if (!Number.isInteger(sequence) || sequence < 1 || sequence > MAX_OBSERVATION_ELEMENTS) {
    refuse('element ref sequence must be an integer within the projection bounds');
  }
  return `el-${String(sequence).padStart(4, '0')}`;
}

export interface ObservationSourceSnapshot {
  readonly origin: unknown;
  readonly elements: readonly ObservationSourceElement[];
}

const MAX_BOUNDS_MAGNITUDE = 10_000_000;
const MAX_ORIGIN_CHARS = 255;
const PROJECTION_ID_PATTERN = /^obs_[0-9a-f]{24}$/;
const ORIGIN_PATTERN = /^https:\/\/[a-z0-9.-]+(?::\d{1,5})?$|^http:\/\/[a-z0-9.-]+(?::\d{1,5})?$/;

const roleAllowlist = new Set<string>(BROWSER_OBSERVATION_ROLE_ALLOWLIST);
const stateAllowlist = new Set<string>(BROWSER_OBSERVATION_STATE_FLAG_ALLOWLIST);
const interactionAllowlist = new Set<string>(BROWSER_OBSERVATION_INTERACTION_FLAG_ALLOWLIST);

function refuse(message: string): never {
  throw new BrowserObservationContractError('contract_violation', message);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Deterministic canonical JSON (sorted keys, no whitespace). The byte budget is
 * measured against exactly this form so the limit cannot drift per call site.
 */
export function canonicalObservationJson(value: unknown): string {
  if (value === null || typeof value === 'number' || typeof value === 'boolean') {
    return JSON.stringify(value);
  }
  if (typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((entry) => canonicalObservationJson(entry)).join(',')}]`;
  }
  if (!isPlainObject(value)) {
    throw new BrowserObservationContractError('contract_violation', 'value is not JSON-canonical');
  }
  const keys = Object.keys(value).sort();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${canonicalObservationJson(value[key])}`)
    .join(',')}}`;
}

/** Bounded, deterministic name truncation that never splits a surrogate pair. */
export function truncateObservationName(name: string): string {
  if (name.length <= MAX_ELEMENT_NAME_CHARS) return name;
  let cut = name.slice(0, MAX_ELEMENT_NAME_CHARS);
  const last = cut.charCodeAt(cut.length - 1);
  if (last >= 0xd800 && last <= 0xdbff) cut = cut.slice(0, -1);
  return cut;
}

function validateFlagList(value: unknown, allowlist: Set<string>, field: string): readonly string[] {
  if (!Array.isArray(value)) refuse(`${field} must be an array of bounded flags`);
  const seen = new Set<string>();
  for (const flag of value) {
    if (typeof flag !== 'string' || !allowlist.has(flag)) {
      refuse(`${field} carries a flag outside the bounded allowlist`);
    }
    seen.add(flag);
  }
  return [...seen].sort();
}

function validateBounds(value: unknown): ObservationElementBounds | null {
  if (!isPlainObject(value)) return null;
  const keys = Object.keys(value).sort();
  if (keys.join(',') !== 'height,width,x,y') return null;
  const numbers = [value.x, value.y, value.width, value.height];
  for (const entry of numbers) {
    if (typeof entry !== 'number' || !Number.isFinite(entry)) return null;
  }
  const [x, y, width, height] = numbers as [number, number, number, number];
  const rounded = { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) };
  for (const entry of [rounded.x, rounded.y, rounded.width, rounded.height]) {
    if (Math.abs(entry) > MAX_BOUNDS_MAGNITUDE) return null;
  }
  if (rounded.width < 0 || rounded.height < 0) return null;
  return rounded;
}

type ProjectedSourceElement = Omit<BoundedObservationElement, 'elementRef'>;

function validateSourceElement(raw: unknown): ProjectedSourceElement | null {
  if (!isPlainObject(raw)) refuse('observation element must be an object');
  for (const key of Object.keys(raw)) {
    if ((BROWSER_OBSERVATION_FORBIDDEN_ELEMENT_KEYS as readonly string[]).includes(key)) {
      refuse(`observation element carries forbidden page-derived key "${key}"`);
    }
  }
  for (const key of Object.keys(raw)) {
    if (!(BROWSER_OBSERVATION_SOURCE_ELEMENT_KEYS as readonly string[]).includes(key)) {
      refuse(`observation element carries an unknown key "${key}"`);
    }
  }
  const credentialField = raw.credentialField;
  if (typeof credentialField !== 'boolean') refuse('credentialField must be a boolean');
  if (typeof raw.name !== 'string') refuse('name must be a string');
  const role = raw.role;
  if (typeof role !== 'string') refuse('role must be a string');

  const bounds = validateBounds(raw.bounds);
  if (bounds === null) return null; // unusable geometry -> unclassifiable
  if (!roleAllowlist.has(role)) return null; // unclassified role -> omitted
  let stateFlags: readonly string[];
  let interactionFlags: readonly string[];
  try {
    stateFlags = validateFlagList(raw.stateFlags, stateAllowlist, 'stateFlags');
    interactionFlags = validateFlagList(raw.interactionFlags, interactionAllowlist, 'interactionFlags');
  } catch {
    return null; // unclassifiable flags -> omitted, never raw-projected
  }
  // Credential-sensitive controls exist on this surface only as the masked marker.
  const name = credentialField ? MASKED_CREDENTIAL_NAME : truncateObservationName(raw.name);
  return Object.freeze({
    role,
    name,
    bounds,
    stateFlags,
    interactionFlags,
    credentialField,
  }) as ProjectedSourceElement;
}

function validateOrigin(value: unknown): string {
  if (typeof value !== 'string') refuse('origin must be a string');
  const origin = value.trim().toLowerCase();
  // Origin only: any path/query/userinfo material — where secrets live — is refused.
  if (origin.length > MAX_ORIGIN_CHARS) {
    refuse(`origin must be at most ${MAX_ORIGIN_CHARS} characters`);
  }
  if (!ORIGIN_PATTERN.test(origin)) {
    refuse('origin must be a bare http(s) origin without path, query or credentials');
  }
  return origin;
}

export function assertProjectionId(value: unknown): string {
  if (typeof value !== 'string' || !PROJECTION_ID_PATTERN.test(value)) {
    refuse('projectionId must be obs_ plus 24 lowercase hex characters');
  }
  return value;
}

/**
 * Project a raw source snapshot into the bounded observation shape.
 *
 * The projection may only ever be produced by the trusted main host; the
 * hostRef pinning is the schema-level half of that guarantee (the process
 * boundary is the other half — no renderer channel exists on this surface).
 */
export function projectBoundedPageObservation(input: {
  readonly projectionId: string;
  readonly source: ObservationSourceSnapshot;
}): BoundedPageObservation {
  const projectionId = assertProjectionId(input.projectionId);
  const originRef = validateOrigin(input.source.origin);
  if (!Array.isArray(input.source.elements)) refuse('observation elements must be an array');

  const elements: BoundedObservationElement[] = [];
  let omittedElements = 0;
  for (const raw of input.source.elements) {
    const projected = validateSourceElement(raw);
    if (projected === null) {
      omittedElements += 1;
      continue;
    }
    if (elements.length < MAX_OBSERVATION_ELEMENTS) {
      elements.push(
        Object.freeze({ ...projected, elementRef: observationElementRef(elements.length + 1) }),
      );
    }
  }
  const classifiedCount = elements.length;
  let truncated = input.source.elements.length - omittedElements > classifiedCount;
  const observation: BoundedPageObservation = Object.freeze({
    projectionId,
    hostRef: BROWSER_OBSERVATION_HOST_REF,
    originRef,
    elementCount: elements.length,
    omittedElements,
    truncated,
    elements,
    pageContentIncluded: false,
    cookieIncluded: false,
    credentialValueIncluded: false,
    domApiExposed: false,
  });
  // Byte budget: deterministic bounded truncation. Whole trailing elements are
  // dropped (document order preserved) until the canonical serialization fits;
  // only a projection whose metadata alone exceeds the budget fails closed.
  let encoded = serializeBoundedPageObservation(observation);
  while (Buffer.byteLength(encoded, 'utf8') > MAX_SERIALIZED_OBSERVATION_BYTES && elements.length > 0) {
    elements.pop();
    truncated = true;
    const bounded: BoundedPageObservation = { ...observation, truncated, elementCount: elements.length, elements };
    encoded = serializeBoundedPageObservation(Object.freeze(bounded));
  }
  if (Buffer.byteLength(encoded, 'utf8') > MAX_SERIALIZED_OBSERVATION_BYTES) {
    throw new BrowserObservationContractError(
      'projection_exceeds_byte_budget',
      `bounded observation exceeds ${MAX_SERIALIZED_OBSERVATION_BYTES} serialized bytes`,
    );
  }
  if (truncated) {
    return Object.freeze({ ...observation, truncated, elementCount: elements.length, elements });
  }
  return observation;
}

/** The one external serialization of the projection (canonical, byte-measured). */
export function serializeBoundedPageObservation(observation: BoundedPageObservation): string {
  return canonicalObservationJson(observation);
}
