import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createPrivateKey, createPublicKey } from 'node:crypto';
import { runBootstrap } from '../bootstrap-deploy.mjs';

test('bootstrap streams fresh secrets through stdin only and publishes matching public key', async () => {
  let call, payload;
  const launch = (executable, args, options) => {
    const process = new EventEmitter();
    process.stderr = new EventEmitter();
    process.stdin = { end(body) { payload = body; queueMicrotask(() => process.emit('close', 0)); } };
    call = { executable, args, options };
    return process;
  };
  await runBootstrap({ launch });
  const secrets = JSON.parse(payload);
  assert.equal(Object.keys(secrets).length, 3);
  assert.deepEqual(call.options.stdio, ['pipe', 'ignore', 'pipe']);
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

test('failure diagnostics survive while generated secrets split across chunks are redacted', async () => {
  let output = '', values;
  const launch = () => {
    const child = new EventEmitter(); child.stderr = new EventEmitter();
    child.stdin = { end(body) {
      values = JSON.parse(body);
      const privatePart = JSON.parse(values.PADIEM_AUTH_ES256_PRIVATE_JWK).d;
      const line = `synthetic failure: ${values.PADIEM_AUTH_IDENTITY_HMAC_KEY} ${privatePart} ${JSON.stringify(values.PADIEM_AUTH_ES256_PRIVATE_JWK)}\n`;
      queueMicrotask(() => { child.stderr.emit('data', line.slice(0, 30)); child.stderr.emit('data', line.slice(30)); child.emit('close', 7); });
    } };
    return child;
  };
  await assert.rejects(() => runBootstrap({ launch, emitError: s => { output += s; } }), /exit 7/);
  assert.match(output, /synthetic failure/);
  assert.match(output, /\[REDACTED\]/);
  for (const secret of Object.values(values)) assert.equal(output.includes(secret), false);
  assert.equal(output.includes(JSON.parse(values.PADIEM_AUTH_ES256_PRIVATE_JWK).d), false);
});
