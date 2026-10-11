/**
 * #3611 — Desktop browser-open redemption transport tests.
 *
 * Hermetic: the supervised pipe is a boundary double, so no resident process, no
 * Electron, no network and no real profile is involved. These tests are about the
 * *wire* contract and, above all, about the fact that the Desktop cannot redeem
 * anything the agent-side durable authority refuses.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  BROWSER_OPEN_REDEMPTION_CARRIES_CREDENTIAL,
  BROWSER_OPEN_REDEMPTION_CARRIES_P01_PAYLOAD,
  BROWSER_OPEN_REDEMPTION_CARRIES_PAGE_CONTENT,
  BROWSER_OPEN_REDEMPTION_CARRIES_RAW_URL,
  BROWSER_OPEN_REDEMPTION_EVENT,
  BROWSER_OPEN_REDEMPTION_NEW_LISTENER,
  BROWSER_OPEN_REDEMPTION_REQUEST_CONTRACT_VERSION,
  BROWSER_OPEN_REDEMPTION_RESPONSE_CONTRACT_VERSION,
  BROWSER_OPEN_REDEMPTION_SECOND_READER,
  BROWSER_OPEN_REDEMPTION_USES_EXISTING_PIPE,
  browserOpenRedemptionRequestLine,
  createResidentBrowserOpenRedemptionPort,
  parseBrowserOpenRedemptionLine,
  type ResidentBrowserOpenRedemptionBoundary,
} from '../src/conversation/resident-browser-open-redemption.js';
import { BrowserOpenRefusalError } from '../src/browser/browser-open-host.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(here, '..', '..', 'src');

const CORRELATION = Object.freeze({
  redemptionRef: 'command.3611.open.1',
  requestFingerprint: 'a'.repeat(64),
  openId: 'open_1',
  runRef: 'run_3611',
});

function answerLine(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    event: BROWSER_OPEN_REDEMPTION_EVENT,
    contract_version: BROWSER_OPEN_REDEMPTION_RESPONSE_CONTRACT_VERSION,
    ok: true,
    redemption_ref: CORRELATION.redemptionRef,
    request_fingerprint: CORRELATION.requestFingerprint,
    ...overrides,
  });
}

class FakeBoundary implements ResidentBrowserOpenRedemptionBoundary {
  sent: string[] = [];
  answer: string | null = null;
  running = true;
  sendOk = true;

  sendResidentLine(line: string): boolean {
    this.sent.push(line);
    return this.sendOk;
  }

  takeResidentBrowserOpenRedemptionLine(): string | null {
    const line = this.answer;
    this.answer = null;
    return line;
  }

  residentRunning(): boolean {
    return this.running;
  }
}

function portWith(boundary: FakeBoundary) {
  return createResidentBrowserOpenRedemptionPort({
    boundary,
    timeoutMs: 1_000,
    pollIntervalMs: 0,
    sleep: async () => undefined,
  });
}

test('#3611 the request carries only the four correlation fields', () => {
  const line = browserOpenRedemptionRequestLine(CORRELATION);
  const parsed = JSON.parse(line) as Record<string, unknown>;
  assert.deepEqual(
    Object.keys(parsed).sort(),
    ['contract_version', 'openId', 'redemptionRef', 'request', 'requestFingerprint', 'runRef'].sort(),
  );
  assert.equal(parsed['request'], BROWSER_OPEN_REDEMPTION_EVENT);
  assert.equal(parsed['contract_version'], BROWSER_OPEN_REDEMPTION_REQUEST_CONTRACT_VERSION);
  for (const forbidden of ['url', 'normalizedUrl', 'pause', 'decision', 'credential', 'cookies']) {
    assert.equal(Object.hasOwn(parsed, forbidden), false, `request must not carry ${forbidden}`);
  }
});

test('#3611 a request with no bounded correlation is refused before sending', async () => {
  const boundary = new FakeBoundary();
  const port = portWith(boundary);
  for (const bad of [
    { ...CORRELATION, redemptionRef: 'has space' },
    { ...CORRELATION, openId: '' },
    { ...CORRELATION, requestFingerprint: 'x'.repeat(600) },
  ]) {
    await assert.rejects(
      () => port.redeem(bad),
      (error: unknown) => error instanceof BrowserOpenRefusalError,
    );
  }
  assert.equal(boundary.sent.length, 0);
});

test('#3611 a successful answer resolves the redemption', async () => {
  const boundary = new FakeBoundary();
  boundary.answer = answerLine();
  await portWith(boundary).redeem(CORRELATION);
  assert.equal(boundary.sent.length, 1);
});

test('#3611 a refused answer rejects with the bounded reason', async () => {
  const boundary = new FakeBoundary();
  boundary.answer = answerLine({ ok: false, reason: 'command_already_started' });
  await assert.rejects(
    () => portWith(boundary).redeem(CORRELATION),
    (error: unknown) =>
      error instanceof BrowserOpenRefusalError &&
      error.message.includes('command_already_started'),
  );
});

test('#3611 an answer for a different open is never accepted', async () => {
  const boundary = new FakeBoundary();
  boundary.answer = answerLine({ request_fingerprint: 'b'.repeat(64) });
  await assert.rejects(
    () => portWith(boundary).redeem(CORRELATION),
    (error: unknown) =>
      error instanceof BrowserOpenRefusalError &&
      error.message.includes('different open'),
  );
});

test('#3611 a not-running resident fails closed instead of waiting', async () => {
  const boundary = new FakeBoundary();
  boundary.running = false;
  await assert.rejects(
    () => portWith(boundary).redeem(CORRELATION),
    (error: unknown) =>
      error instanceof BrowserOpenRefusalError && error.code === 'redemption_unavailable',
  );
});

test('#3611 an unwritable resident pipe fails closed', async () => {
  const boundary = new FakeBoundary();
  boundary.sendOk = false;
  await assert.rejects(
    () => portWith(boundary).redeem(CORRELATION),
    (error: unknown) =>
      error instanceof BrowserOpenRefusalError && error.code === 'redemption_unavailable',
  );
});

test('#3611 the response schema is exact-closed', () => {
  assert.notEqual(parseBrowserOpenRedemptionLine(answerLine()), null);
  // An extra key is not this contract, even when the extra would be discarded.
  assert.equal(parseBrowserOpenRedemptionLine(answerLine({ note: 'extra' })), null);
  // A different event or version is not this contract either.
  assert.equal(parseBrowserOpenRedemptionLine(answerLine({ event: 'something_else' })), null);
  assert.equal(parseBrowserOpenRedemptionLine(answerLine({ contract_version: 'v0' })), null);
  // The reason is bounded to a code, never a payload.
  const refused = parseBrowserOpenRedemptionLine(answerLine({ ok: false, reason: 'x' }));
  assert.notEqual(refused, null);
  assert.equal(refused?.reason, 'x');
});

test('#3611 the transport reuses the existing supervised pipe and adds no reader', () => {
  assert.equal(BROWSER_OPEN_REDEMPTION_USES_EXISTING_PIPE, true);
  assert.equal(BROWSER_OPEN_REDEMPTION_NEW_LISTENER, false);
  assert.equal(BROWSER_OPEN_REDEMPTION_SECOND_READER, false);
  assert.equal(BROWSER_OPEN_REDEMPTION_CARRIES_RAW_URL, false);
  assert.equal(BROWSER_OPEN_REDEMPTION_CARRIES_P01_PAYLOAD, false);
  assert.equal(BROWSER_OPEN_REDEMPTION_CARRIES_CREDENTIAL, false);
  assert.equal(BROWSER_OPEN_REDEMPTION_CARRIES_PAGE_CONTENT, false);
});

test('#3611 the transport never opens a socket or a listener', () => {
  for (const file of [
    path.join('conversation', 'resident-browser-open-redemption.ts'),
    path.join('browser', 'browser-open-composition.ts'),
  ]) {
    const source = readFileSync(path.join(sourceRoot, file), 'utf8');
    for (const forbidden of [
      "from 'node:net'",
      "from 'node:http'",
      'createServer(',
      'listen(',
      "from 'electron'",
    ]) {
      assert.equal(source.includes(forbidden), false, `${file} must not contain ${forbidden}`);
    }
  }
});
