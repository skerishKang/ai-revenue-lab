// Test support (#7541): the identity authority's real product boundary.
//
// The common login asks the identity authority for an account number the first
// time it sees a person, and sends the client id as the product id. The
// authority admits only its reviewed products. The fakes in these tests used to
// answer for any product, so a registered client the authority does not admit
// passed here and failed in production with a 503 on every first login.
//
// Nothing below restates the product list. It is read from the authority's own
// source, and the registered clients are read from this Worker's own config, so
// a change to either one is what these tests run against.
import { readFileSync } from 'node:fs';

const repo = new URL('../../../', import.meta.url);
const read = path => readFileSync(new URL(path, repo), 'utf8');

const boundary = read('packages/padiem-control-plane/identity_authority_worker.py')
  .match(/^_ALLOWED_PRODUCTS: frozenset\[str\] = frozenset\(\{([^}]*)\}\)/m);
if (!boundary) throw new Error('identity authority product boundary not found in its source');

/** Product ids the identity authority admits for an account link. */
export const AUTHORITY_PRODUCTS = Object.freeze(
  boundary[1].split(',').map(value => value.trim().replace(/^["']|["']$/g, '')).filter(Boolean)
);

const registered = read('apps/padiem-auth/wrangler.toml').match(/^PADIEM_AUTH_CLIENTS = '''(.*)'''$/m);
if (!registered) throw new Error('registered common-login clients not found in the Worker config');

/** Client ids registered with the common login. */
export const REGISTERED_CLIENTS = Object.freeze(Object.keys(JSON.parse(registered[1])));

/** Registered clients that are deliberately not identity products, with the reason. */
export const NOT_AN_IDENTITY_PRODUCT = Object.freeze(
  JSON.parse(read('apps/padiem-auth/test/identity-product-exclusions.json'))
);

/** The authority's closed answer for a product outside its boundary. */
export const PRODUCT_MISMATCH = Object.freeze({
  ok: false,
  error: { code: 'identity_authority_product_mismatch', message: 'Canonical identity request was rejected' },
});

/**
 * Put the real product boundary in front of a fake authority. A request for a
 * product the authority does not admit gets the authority's own refusal and
 * never reaches the fake.
 */
export function withProductBoundary(authority) {
  return {
    ...authority,
    async resolve_or_create_product_link(request) {
      if (!AUTHORITY_PRODUCTS.includes(request?.product_id)) return structuredClone(PRODUCT_MISMATCH);
      return authority.resolve_or_create_product_link(request);
    },
  };
}
