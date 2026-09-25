import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DENIED_IPC_CHANNELS,
  IPC_ALLOWLIST,
  IPC_CHANNELS,
  IPC_SECURITY,
  IpcContractError,
  assertAllowedIpcChannel,
  isAllowedIpcChannel,
} from '../src/contract/ipc.js';

test('#3083 IPC surface is exactly the six declared allowlisted channels', () => {
  assert.deepEqual([...IPC_CHANNELS].sort(), [
    'padiem:shell:get-bounded-log',
    'padiem:shell:get-status',
    'padiem:shell:pairing-deeplink-submit',
    'padiem:shell:runner-health',
    'padiem:shell:runner-start',
    'padiem:shell:runner-stop',
  ]);
  assert.equal(IPC_ALLOWLIST.size, 6);
  assert.equal(IPC_SECURITY.ALLOWLIST_SIZE, 6);
});

test('#3083 IPC security posture forbids generic invoke, raw shell and renderer credentials', () => {
  assert.equal(IPC_SECURITY.CONTEXT_ISOLATION, true);
  assert.equal(IPC_SECURITY.NODE_INTEGRATION, false);
  assert.equal(IPC_SECURITY.SANDBOX, true);
  assert.equal(IPC_SECURITY.NO_GENERIC_INVOKE_COMMAND_ARGS, true);
  assert.equal(IPC_SECURITY.NO_ARBITRARY_CHANNEL_PASSTHROUGH, true);
  assert.equal(IPC_SECURITY.NO_RAW_SHELL_TERMINAL, true);
  assert.equal(IPC_SECURITY.RENDERER_CREDENTIAL_AUTHORITY, false);
});

test('#3083 every denied generic/exec channel is refused by the allowlist', () => {
  for (const channel of DENIED_IPC_CHANNELS) {
    assert.equal(
      isAllowedIpcChannel(channel),
      false,
      `denied channel must not be allowed: ${channel}`,
    );
    assert.throws(
      () => assertAllowedIpcChannel(channel),
      (error: unknown) =>
        error instanceof IpcContractError && /not in static allowlist/.test(error.message),
      `denied channel must throw: ${channel}`,
    );
  }
});

test('#3083 wildcards, prototypes and non-strings are refused', () => {
  const hostile: unknown[] = [
    '*',
    'padiem:shell:*',
    'padiem:shell:get-status ',
    ' PADIEM:SHELL:GET-STATUS',
    'toString',
    'constructor',
    '__proto__',
    '',
    null,
    undefined,
    42,
    { channel: 'padiem:shell:get-status' },
    ['padiem:shell:get-status'],
  ];
  for (const candidate of hostile) {
    assert.equal(isAllowedIpcChannel(candidate), false, `must refuse: ${String(candidate)}`);
  }
});

test('#3083 allowed channels resolve to themselves and nothing else does', () => {
  for (const channel of IPC_CHANNELS) {
    assert.equal(assertAllowedIpcChannel(channel), channel);
  }
  const allowed = [...IPC_ALLOWLIST];
  assert.equal(allowed.every((channel) => channel.startsWith('padiem:shell:')), true);
  assert.equal(
    allowed.some((channel) => channel === 'padiem:shell:invoke' || channel.endsWith('*')),
    false,
  );
});
