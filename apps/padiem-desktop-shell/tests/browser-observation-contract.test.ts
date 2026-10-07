/**
 * #3629 — bounded page-observation contract tests (owner decision #3609).
 *
 * Hermetic: no Electron, no network, no browser, no page. Every deny-list rule
 * from the D1=ENABLED_BOUNDED decision is exercised at the exact-key level so
 * a future edit that widens the projection fails here rather than in review.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BROWSER_OBSERVATION_HOST_REF,
  MASKED_CREDENTIAL_NAME,
  MAX_ELEMENT_NAME_CHARS,
  MAX_OBSERVATION_ELEMENTS,
  MAX_SERIALIZED_OBSERVATION_BYTES,
  BrowserObservationContractError,
  canonicalObservationJson,
  observationElementRef,
  projectBoundedPageObservation,
  serializeBoundedPageObservation,
  truncateObservationName,
  type BoundedPageObservation,
  type ObservationSourceElement,
} from '../src/browser/browser-observation-contract.js';
import {
  BROWSER_CONTROL_IMPLEMENTED,
  BROWSER_OPEN_PAGE_DERIVED_OUTPUT_SUPPORTED,
} from '../src/browser/browser-open-host.js';
import { BROWSER_OPEN_RECEIPT_FIELDS } from '../src/browser/browser-open-contracts.js';

const PROJECTION_ID = 'obs_aaaaaaaaaaaaaaaaaaaaaaaa';

function sourceElement(overrides: Record<string, unknown> = {}): ObservationSourceElement {
  return {
    role: 'button',
    name: '제출',
    bounds: { x: 1, y: 2, width: 30, height: 20 },
    stateFlags: ['focusable'],
    interactionFlags: ['clickable'],
    credentialField: false,
    ...overrides,
  } as ObservationSourceElement;
}

function project(
  elements: readonly ObservationSourceElement[],
  origin = 'https://example.com',
): BoundedPageObservation {
  return projectBoundedPageObservation({
    projectionId: PROJECTION_ID,
    source: { origin, elements },
  });
}

test('ordinary button, textbox and link elements project with bounded fields', () => {
  const observation = project([
    sourceElement({ role: 'button', name: '저장' }),
    sourceElement({ role: 'textbox', name: '이름', interactionFlags: ['typeable', 'editable'] }),
    sourceElement({ role: 'link', name: 'Docs' }),
  ]);
  assert.equal(observation.elementCount, 3);
  assert.equal(observation.truncated, false);
  assert.equal(observation.omittedElements, 0);
  assert.equal(observation.hostRef, BROWSER_OBSERVATION_HOST_REF);
  assert.equal(observation.originRef, 'https://example.com');
  assert.deepEqual(
    observation.elements.map((element) => element.elementRef),
    ['el-0001', 'el-0002', 'el-0003'],
  );
  assert.deepEqual(
    observation.elements.map((element) => element.role),
    ['button', 'textbox', 'link'],
  );
  assert.equal(observation.elements[0]?.name, '저장');
  assert.deepEqual(observation.elements[0]?.bounds, { x: 1, y: 2, width: 30, height: 20 });
  assert.deepEqual(observation.elements[0]?.stateFlags, ['focusable']);
  assert.deepEqual(observation.elements[0]?.interactionFlags, ['clickable']);
  assert.equal(observation.pageContentIncluded, false);
  assert.equal(observation.cookieIncluded, false);
  assert.equal(observation.credentialValueIncluded, false);
  assert.equal(observation.domApiExposed, false);
});

test('more than 400 elements truncate deterministically with a declared flag', () => {
  const elements = Array.from({ length: MAX_OBSERVATION_ELEMENTS + 40 }, (_v, index) =>
    sourceElement({ name: `버튼 ${index + 1}` }),
  );
  const observation = project(elements);
  assert.equal(observation.truncated, true);
  assert.ok(observation.elementCount <= MAX_OBSERVATION_ELEMENTS);
  assert.ok(observation.elementCount >= 1);
  assert.equal(observation.elements[0]?.elementRef, 'el-0001');
  assert.equal(observation.elements[0]?.name, '버튼 1');
  const last = observation.elements[observation.elements.length - 1];
  assert.equal(last?.elementRef, `el-${String(observation.elementCount).padStart(4, '0')}`);
  assert.ok(
    Buffer.byteLength(serializeBoundedPageObservation(observation), 'utf8') <=
      MAX_SERIALIZED_OBSERVATION_BYTES,
  );
});

test('serialized output beyond 8192 bytes truncates whole elements, never bytes', () => {
  const elements = Array.from({ length: 100 }, () =>
    sourceElement({ name: 'x'.repeat(MAX_ELEMENT_NAME_CHARS) }),
  );
  const observation = project(elements);
  assert.equal(observation.truncated, true);
  assert.ok(observation.elementCount < 100);
  assert.ok(
    Buffer.byteLength(serializeBoundedPageObservation(observation), 'utf8') <=
      MAX_SERIALIZED_OBSERVATION_BYTES,
  );
});

test('the serialized byte budget is enforced with whole-element truncation', () => {
  // A pathological origin is bounded, so the fail-closed byte branch can only
  // ever be defense-in-depth: every reachable overflow truncates whole
  // trailing elements deterministically instead of cutting bytes.
  assert.throws(
    () => project([], `https://${'a'.repeat(400)}.com`),
    (error: unknown) =>
      error instanceof BrowserObservationContractError && error.code === 'contract_violation',
  );
});

test('element names truncate to 64 characters without splitting surrogate pairs', () => {
  assert.equal(truncateObservationName('a'.repeat(100)).length, MAX_ELEMENT_NAME_CHARS);
  // BMP hangul has no surrogate pairs: 40 chars stay 40.
  assert.equal(truncateObservationName('가'.repeat(40)), '가'.repeat(40));
  // Astral plane: a cut landing between the code units of one pair trims it.
  const astral = `a${'𝄞'.repeat(32)}`; // 65 UTF-16 code units
  const cut = truncateObservationName(astral);
  assert.ok(cut.length <= MAX_ELEMENT_NAME_CHARS);
  assert.ok(!/[\ud800-\udbff]$/.test(cut), 'truncated name must not end mid-pair');
  const observation = project([sourceElement({ name: 'a'.repeat(100) })]);
  assert.equal(observation.elements[0]?.name.length, MAX_ELEMENT_NAME_CHARS);
});

test('password input values are never projected: the credential marker replaces the name', () => {
  const observation = project([
    sourceElement({ role: 'textbox', name: 'hunter2 secret', credentialField: true }),
  ]);
  assert.equal(observation.elements[0]?.credentialField, true);
  assert.equal(observation.elements[0]?.name, MASKED_CREDENTIAL_NAME);
  assert.equal(observation.credentialValueIncluded, false);
});

test('form values, textarea contents and password material are structurally refused', () => {
  for (const forbidden of ['value', 'values', 'formValues', 'text', 'content']) {
    assert.throws(
      () => project([sourceElement({ [forbidden]: 'typed-secret' })]),
      (error: unknown) =>
        error instanceof BrowserObservationContractError && error.code === 'contract_violation',
      `forbidden key ${forbidden} must refuse the projection`,
    );
  }
});

test('cookie, localStorage and sessionStorage material are structurally refused', () => {
  for (const forbidden of ['cookies', 'localStorage', 'sessionStorage']) {
    assert.throws(
      () => project([sourceElement({ [forbidden]: { session: 'token' } })]),
      (error: unknown) =>
        error instanceof BrowserObservationContractError && error.code === 'contract_violation',
      `forbidden key ${forbidden} must refuse the projection`,
    );
  }
});

test('raw DOM, raw HTML and page-source keys are structurally refused', () => {
  for (const forbidden of ['dom', 'html', 'source']) {
    assert.throws(
      () => project([sourceElement({ [forbidden]: '<html></html>' })]),
      (error: unknown) =>
        error instanceof BrowserObservationContractError && error.code === 'contract_violation',
      `forbidden key ${forbidden} must refuse the projection`,
    );
  }
});

test('arbitrary attributes are refused: only the exact declared key set validates', () => {
  for (const extra of ['data-foo', 'ariaLabel', 'style', 'className', 'id', 'placeholder']) {
    assert.throws(
      () => project([sourceElement({ [extra]: 'anything' })]),
      (error: unknown) =>
        error instanceof BrowserObservationContractError && error.code === 'contract_violation',
      `unknown key ${extra} must refuse the projection`,
    );
  }
});

test('screenshot, image and pdf keys are structurally refused', () => {
  for (const forbidden of ['screenshot', 'image', 'pdf']) {
    assert.throws(
      () => project([sourceElement({ [forbidden]: 'bytes' })]),
      (error: unknown) =>
        error instanceof BrowserObservationContractError && error.code === 'contract_violation',
      `forbidden key ${forbidden} must refuse the projection`,
    );
  }
});

test('unclassifiable elements are omitted deterministically, never raw-projected', () => {
  const observation = project([
    sourceElement({ role: 'mystery-widget' }),
    sourceElement({ role: 'button' }),
    sourceElement({ stateFlags: ['warp-speed'] }),
    sourceElement({ bounds: { x: 'far', y: 0, width: 1, height: 1 } }),
  ]);
  assert.equal(observation.elementCount, 1);
  assert.equal(observation.omittedElements, 3);
  assert.equal(observation.elements[0]?.elementRef, 'el-0001');
  assert.equal(observation.elements[0]?.role, 'button');
});

test('element refs are stable across identical observations and derived only from order', () => {
  const elements = [sourceElement(), sourceElement({ role: 'link', name: 'A' })];
  const first = project(elements);
  const second = project(elements);
  assert.equal(serializeBoundedPageObservation(first), serializeBoundedPageObservation(second));
  assert.equal(observationElementRef(1), 'el-0001');
  assert.equal(observationElementRef(MAX_OBSERVATION_ELEMENTS), 'el-0400');
  assert.throws(() => observationElementRef(0));
  assert.throws(() => observationElementRef(MAX_OBSERVATION_ELEMENTS + 1));
});

test('origin ref is a bare http(s) origin: path, query and credential material refuse', () => {
  assert.throws(() => project([sourceElement()], 'https://example.com/path?token=secret'));
  assert.throws(() => project([sourceElement()], 'https://user:pass@example.com'));
  assert.throws(() => project([sourceElement()], 'file:///etc/passwd'));
  assert.throws(() => project([sourceElement()], 'javascript:alert(1)'));
  assert.equal(project([sourceElement()], 'https://example.com').originRef, 'https://example.com');
  assert.equal(project([sourceElement()], 'http://example.com:8080').originRef, 'http://example.com:8080');
});

test('malformed projection ids and payloads refuse', () => {
  assert.throws(() =>
    projectBoundedPageObservation({
      projectionId: 'renderer-supplied-id',
      source: { origin: 'https://example.com', elements: [] },
    }),
  );
  assert.throws(() =>
    project('not-an-object' as unknown as ObservationSourceElement[]),
  );
});

test('serialization is canonical (sorted keys, no whitespace) and byte-measured', () => {
  const encoded = canonicalObservationJson({ b: 1, a: [2, { d: 3, c: 4 }] });
  assert.equal(encoded, '{"a":[2,{"c":4,"d":3}],"b":1}');
  const observation = project([sourceElement()]);
  const bytes = Buffer.byteLength(serializeBoundedPageObservation(observation), 'utf8');
  assert.ok(bytes > 0 && bytes <= MAX_SERIALIZED_OBSERVATION_BYTES);
});

test('browser.open byte-zero contract is unchanged by the observation slice', () => {
  assert.equal(BROWSER_OPEN_PAGE_DERIVED_OUTPUT_SUPPORTED, false);
  assert.equal(BROWSER_CONTROL_IMPLEMENTED, false);
  assert.ok(!BROWSER_OPEN_RECEIPT_FIELDS.includes('observation' as never));
  assert.ok(!BROWSER_OPEN_RECEIPT_FIELDS.includes('elements' as never));
});
