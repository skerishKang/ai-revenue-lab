import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createVerifier } from '../verify.mjs';
const vector = JSON.parse(await readFile(new URL('./vectors.json', import.meta.url)));
test('shared ES256 vectors and cached JWKS', async () => {
  let calls = 0;
  const verify = createVerifier({ audience: vector.audience, clock: () => vector.now * 1000, fetcher: async (url) => { assert.equal(url, 'https://auth.padiem.net/.well-known/jwks.json'); calls++; return Response.json(vector.jwks); } });
  assert.equal((await verify(vector.tokens.valid)).accountId, 'sub_existing');
  for (const name of ['wrong_audience', 'wrong_issuer', 'expired', 'forged']) await assert.rejects(() => verify(vector.tokens[name]));
  assert.equal(calls, 1);
});
