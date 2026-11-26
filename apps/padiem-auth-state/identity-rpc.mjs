const encoder = new TextEncoder();
const epoch = () => Math.floor(Date.now() / 1000);

async function callSigned({ origin, secret, fetcher, now, path, payload }) {
  if (typeof origin !== 'string' || !/^https:\/\/[^/]+\/?$/.test(origin) ||
      typeof secret !== 'string' || encoder.encode(secret).length < 32) throw new Error('identity rpc configuration missing');
  const body = encoder.encode(JSON.stringify(payload));
  if (!body.length || body.length > 64 * 1024) throw new Error('identity rpc body invalid');
  const at = String(now());
  const serviceId = crypto.randomUUID();
  const prefix = encoder.encode(`v2\nPOST\n${path}\n${at}\n${serviceId}\n`);
  const canonical = new Uint8Array(prefix.length + body.length);
  canonical.set(prefix);
  canonical.set(body, prefix.length);
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signature = new Uint8Array(await crypto.subtle.sign('HMAC', key, canonical));
  const proof = 'v2=' + [...signature].map(byte => byte.toString(16).padStart(2, '0')).join('');
  const response = await fetcher(origin.replace(/\/+$/, '') + path, {
    method: 'POST', redirect: 'manual', body, signal: AbortSignal.timeout(10_000),
    headers: {
      'content-type': 'application/json',
      'x-padiem-service-at': at,
      'x-padiem-service-id': serviceId,
      'x-padiem-service-proof': proof,
    },
  });
  if (!response.ok) throw new Error('identity rpc failed');
  return response.json();
}

function validateConfig({ origin, secret }) {
  if (typeof origin !== 'string' || !/^https:\/\/[^/]+\/?$/.test(origin) ||
      typeof secret !== 'string' || encoder.encode(secret).length < 32) throw new Error('identity rpc configuration missing');
}

export function createIdentityAuthorityRpc({ origin, secret, fetcher = fetch, now = epoch } = {}) {
  validateConfig({ origin, secret });
  const call = (method, payload) => callSigned({ origin, secret, fetcher, now, path: `/internal/auth-state/identity/${method}`, payload });
  return {
    resolve_or_create_identity_subject: payload => call('resolve_or_create_identity_subject', payload),
    resolve_or_create_product_link: payload => call('resolve_or_create_product_link', payload),
    list_active_product_links_for_subject: payload => call('list_active_product_links_for_subject', payload),
  };
}

export function createDeletionRecordRpc({ origin, secret, fetcher = fetch, now = epoch } = {}) {
  validateConfig({ origin, secret });
  return {
    resolve_subject_removed_by_account_deletion: payload => callSigned({
      origin, secret, fetcher, now,
      path: '/internal/auth-state/deletion-record/resolve_subject_removed_by_account_deletion',
      payload,
    }),
  };
}
