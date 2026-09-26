/**
 * #3093 — single-instance ownership and second-instance forwarding tests.
 *
 * Injected fake `app` surface only; no Electron runtime required.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  acquireSingleInstanceOwnership,
  extractDeepLinkArgv,
  type SingleInstanceApp,
} from '../src/main/single-instance.js';

function fakeApp(lock: boolean): {
  app: SingleInstanceApp;
  emitSecond: (argv: string[]) => void;
  secondListeners: Array<(event: unknown, argv: readonly string[]) => void>;
} {
  const secondListeners: Array<(event: unknown, argv: readonly string[]) => void> = [];
  return {
    secondListeners,
    app: {
      requestSingleInstanceLock: () => lock,
      on(event, listener) {
        assert.equal(event, 'second-instance');
        secondListeners.push(listener);
      },
    },
    emitSecond(argv) {
      for (const listener of secondListeners) listener({}, argv);
    },
  };
}

test('#3093 extraction returns the first padiem:// entry, scheme case-insensitive', () => {
  assert.equal(
    extractDeepLinkArgv(['C:\\electron.exe', 'PADiem://pair?challenge=abc']),
    'PADiem://pair?challenge=abc',
  );
});

test('#3093 extraction returns null for argv without a deep link', () => {
  assert.equal(extractDeepLinkArgv(['C:\\electron.exe', '--flag', 'C:\\app']), null);
});

test('#3093 first deep link wins — multiple links are malformed input, not a queue', () => {
  assert.equal(
    extractDeepLinkArgv(['padiem://pair?a=1', 'padiem://pair?b=2']),
    'padiem://pair?a=1',
  );
});

test('#3093 extraction never decodes or normalizes — raw candidate goes to the bounded parser', () => {
  const hostile = 'padiem://pair?x=%2e%2e%2f&y=' + 'A'.repeat(600);
  assert.equal(extractDeepLinkArgv([hostile]), hostile);
});

test('#3093 non-string argv entries are skipped without throwing', () => {
  const argv = ['C:\\electron.exe', 42 as unknown as string, undefined as unknown as string, 'padiem://pair?k=v'];
  assert.equal(extractDeepLinkArgv(argv), 'padiem://pair?k=v');
});

test('#3093 owner registers forwarding and never quits', () => {
  const { app } = fakeApp(true);
  let quit = 0;
  const forwarded: string[] = [];
  const outcome = acquireSingleInstanceOwnership({
    app,
    forwardDeepLink: (link) => forwarded.push(link),
    onNotOwner: () => {
      quit += 1;
    },
  });
  assert.equal(outcome.owner, true);
  assert.equal(quit, 0);
});

test('#3093 non-owner quits and never registers a forwarding hook', () => {
  const { app, secondListeners } = fakeApp(false);
  let quit = 0;
  const outcome = acquireSingleInstanceOwnership({
    app,
    forwardDeepLink: () => assert.fail('non-owner must not forward'),
    onNotOwner: () => {
      quit += 1;
    },
  });
  assert.equal(outcome.owner, false);
  assert.equal(quit, 1);
  assert.equal(secondListeners.length, 0);
});

test('#3093 second-instance deep link is forwarded to the existing intake exactly once', () => {
  const { app, emitSecond } = fakeApp(true);
  const forwarded: string[] = [];
  acquireSingleInstanceOwnership({
    app,
    forwardDeepLink: (link) => forwarded.push(link),
    onNotOwner: () => assert.fail('owner path'),
  });
  emitSecond(['C:\\electron.exe', 'padiem://pair?challenge=zz9', 'C:\\app']);
  assert.deepEqual(forwarded, ['padiem://pair?challenge=zz9']);
});

test('#3093 second-instance without a deep link forwards nothing but still wakes the window', () => {
  const { app, emitSecond } = fakeApp(true);
  let forwarded = 0;
  let woke = 0;
  acquireSingleInstanceOwnership({
    app,
    forwardDeepLink: () => {
      forwarded += 1;
    },
    onNotOwner: () => assert.fail('owner path'),
    onSecondInstance: () => {
      woke += 1;
    },
  });
  emitSecond(['C:\\electron.exe', 'C:\\app']);
  assert.equal(forwarded, 0);
  assert.equal(woke, 1);
});

test('#3093 forwarding carries the raw string only — no parse result crosses this boundary', () => {
  // SECOND_DEEPLINK_PARSER_AUTHORITY=0: this module must hand the SAME raw
  // candidate to the existing intake; interpretation stays in the #3083 parser.
  const { app, emitSecond } = fakeApp(true);
  const raw = 'padiem://pair?token=abc&x=1';
  let seen: string | null = null;
  acquireSingleInstanceOwnership({
    app,
    forwardDeepLink: (link) => {
      seen = link;
    },
    onNotOwner: () => assert.fail('owner path'),
  });
  emitSecond([raw]);
  assert.equal(seen, raw);
});
