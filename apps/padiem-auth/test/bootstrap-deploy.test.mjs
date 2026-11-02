import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createPrivateKey, createPublicKey } from 'node:crypto';
import { redactDiagnostics, runBootstrap } from '../bootstrap-deploy.mjs';

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

test('Cloudflare token and account id never remain in failure diagnostics', async () => {
  const previous = { token: process.env.CLOUDFLARE_API_TOKEN, account: process.env.CLOUDFLARE_ACCOUNT_ID };
  const token = 'synthetic-token+/=value', account = '0123456789abcdef0123456789abcdef';
  process.env.CLOUDFLARE_API_TOKEN = token;
  process.env.CLOUDFLARE_ACCOUNT_ID = account;
  let output = '';
  const launch = () => {
    const child = new EventEmitter(); child.stderr = new EventEmitter();
    child.stdin = { end() { queueMicrotask(() => {
      child.stderr.emit('data', `wrangler failed for ${token} on ${account}\n`);
      child.emit('close', 1);
    }); } };
    return child;
  };
  try {
    await assert.rejects(() => runBootstrap({ launch, emitError: s => { output += s; } }), /exit 1/);
  } finally {
    if (previous.token === undefined) delete process.env.CLOUDFLARE_API_TOKEN; else process.env.CLOUDFLARE_API_TOKEN = previous.token;
    if (previous.account === undefined) delete process.env.CLOUDFLARE_ACCOUNT_ID; else process.env.CLOUDFLARE_ACCOUNT_ID = previous.account;
  }
  assert.match(output, /wrangler failed for/);
  assert.equal(output.includes(token), false);
  assert.equal(output.includes(account), false);
  assert.equal(output.includes(encodeURIComponent(token)), false);
});

test('redactDiagnostics masks raw, JSON-escaped and URI-encoded secret forms', () => {
  const hmac = 'p@ss "quoted" +/=';
  const privateJwk = JSON.stringify({ kty: 'EC', d: 'private-part+/=' });
  const secrets = { PADIEM_AUTH_ES256_PRIVATE_JWK: privateJwk, PADIEM_AUTH_IDENTITY_HMAC_KEY: hmac, PADIEM_AUTH_REFRESH_ENCRYPTION_KEY: 'refresh-value' };
  const text = `raw ${hmac} json ${JSON.stringify(hmac).slice(1, -1)} uri ${encodeURIComponent(hmac)} jwk ${privateJwk} d private-part+/= keep-me`;
  const redacted = redactDiagnostics(text, secrets);
  assert.match(redacted, /keep-me/);
  assert.equal(redacted.includes(hmac), false);
  assert.equal(redacted.includes(JSON.stringify(hmac).slice(1, -1)), false);
  assert.equal(redacted.includes(encodeURIComponent(hmac)), false);
  assert.equal(redacted.includes(privateJwk), false);
  assert.equal(redacted.includes('private-part+/='), false);
  assert.equal(redacted.includes('refresh-value'), false);
});
