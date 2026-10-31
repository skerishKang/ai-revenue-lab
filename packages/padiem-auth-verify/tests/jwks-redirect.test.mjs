import test from 'node:test';
import assert from 'node:assert/strict';
import { createVerifier } from '../verify.mjs';
test('verification does not follow JWKS redirects', async () => {
  const b64 = x => Buffer.from(JSON.stringify(x)).toString('base64url');
  const verify = createVerifier({audience:'lovetree-4-0',fetcher:async (_url, init) => {
    assert.equal(init.redirect, 'manual');
    return new Response(null, {status:302, headers:{location:'https://evil.example'}});
  }});
  await assert.rejects(verify(`${b64({alg:'ES256',typ:'JWT',kid:'test'})}.${b64({})}.AA`), /jwks_unavailable/);
});
