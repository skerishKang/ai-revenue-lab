import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createPrivateKey, createPublicKey } from 'node:crypto';
import { runBootstrap } from '../bootstrap-deploy.mjs';

test('bootstrap streams fresh secrets through stdin only and publishes matching public key', async () => {
  let call, payload;
  const launch = (executable, args, options) => {
    const process = new EventEmitter();
    process.stdin = { end(body) { payload = body; queueMicrotask(() => process.emit('close', 0)); } };
    call = { executable, args, options };
    return process;
  };
  await runBootstrap({ launch });
  const secrets = JSON.parse(payload);
  assert.equal(Object.keys(secrets).length, 3);
  assert.deepEqual(call.options.stdio, ['pipe', 'ignore', 'ignore']);
  assert.equal(call.executable, 'bash');
  assert.equal(call.args[call.args.indexOf('--secrets-file') + 1], '/dev/stdin');
  for (const value of Object.values(secrets)) assert.equal(call.args.some(arg => arg.includes(value)), false);
  const key = createPrivateKey({ key: JSON.parse(secrets.PADIEM_AUTH_ES256_PRIVATE_JWK), format: 'jwk' });
  const pub = createPublicKey(key).export({ format: 'jwk' });
  const arg = call.args.find(x => x.startsWith('PADIEM_AUTH_JWKS:'));
  const jwk = JSON.parse(arg.slice('PADIEM_AUTH_JWKS:'.length)).keys[0];
  assert.equal(pub.x, jwk.x); assert.equal(pub.y, jwk.y); assert.equal('d' in jwk, false);
  assert.equal(Buffer.from(secrets.PADIEM_AUTH_IDENTITY_HMAC_KEY, 'base64url').length, 32);
  assert.equal(Buffer.from(secrets.PADIEM_AUTH_REFRESH_ENCRYPTION_KEY, 'base64url').length, 32);
});
