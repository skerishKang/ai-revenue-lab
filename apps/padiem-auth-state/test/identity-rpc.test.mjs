import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createDeletionRecordRpc, createIdentityAuthorityRpc } from '../identity-rpc.mjs';

const identitySecret = 'synthetic-identity-rpc-secret-at-least-32-bytes';
const deletionSecret = 'synthetic-deletion-rpc-secret-at-least-32-bytes';

function verifyV2(secret, url, init) {
  const path = new URL(url).pathname;
  const body = Buffer.from(init.body);
  const expected = 'v2=' + createHmac('sha256', secret).update(Buffer.concat([
    Buffer.from(`v2\nPOST\n${path}\n${init.headers['x-padiem-service-at']}\n${init.headers['x-padiem-service-id']}\n`),
    body,
  ])).digest('hex');
  assert.equal(init.headers['x-padiem-service-proof'], expected);
  assert.equal(init.redirect, 'manual');
  assert.ok(init.signal);
}

test('identity adapter exposes only the three dedicated methods and signs v2 requests', async () => {
  const calls = [];
  const rpc = createIdentityAuthorityRpc({
    origin: 'https://identity.example.invalid', secret: identitySecret, now: () => 1000,
    fetcher: async (url, init) => { calls.push({ url, init }); return Response.json({ ok: false, error: { code: 'identity_rebind_forbidden' } }); },
  });
  assert.deepEqual(Object.keys(rpc).sort(), [
    'list_active_product_links_for_subject', 'resolve_or_create_identity_subject', 'resolve_or_create_product_link',
  ]);
  const result = await rpc.resolve_or_create_product_link({ product_id: 'b62', product_user_id: 'usr_synthetic' });
  assert.equal(result.error.code, 'identity_rebind_forbidden');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://identity.example.invalid/internal/auth-state/identity/resolve_or_create_product_link');
  verifyV2(identitySecret, calls[0].url, calls[0].init);
});

test('deletion record adapter uses its own path and secret', async () => {
  let captured;
  const rpc = createDeletionRecordRpc({
    origin: 'https://identity.example.invalid', secret: deletionSecret, now: () => 1000,
    fetcher: async (url, init) => { captured = { url, init }; return Response.json({ ok: true, removed_by_account_deletion: true }); },
  });
  assert.deepEqual(await rpc.resolve_subject_removed_by_account_deletion({ canonical_subject_id: 'sub_synthetic' }), { ok: true, removed_by_account_deletion: true });
  assert.equal(captured.url, 'https://identity.example.invalid/internal/auth-state/deletion-record/resolve_subject_removed_by_account_deletion');
  verifyV2(deletionSecret, captured.url, captured.init);
});

test('identity transport failures are thrown rather than converted to domain answers', async () => {
  const rpc = createIdentityAuthorityRpc({
    origin: 'https://identity.example.invalid', secret: identitySecret,
    fetcher: async () => Response.json({ ok: false }, { status: 503 }),
  });
  await assert.rejects(() => rpc.list_active_product_links_for_subject({ canonical_subject_id: 'sub_synthetic' }), /identity rpc failed/);
  assert.throws(() => createIdentityAuthorityRpc({ origin: 'http://identity.example.invalid', secret: identitySecret }), /configuration missing/);
});
