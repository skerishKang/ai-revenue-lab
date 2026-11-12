import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Read the simple scalar/array binding tables from the deployed TOML. Other
// tables (including multiline client JSON) are outside this configuration test.
function bindingTables() {
  const names = new Set(['', 'services', 'durable_objects.bindings', 'migrations',
    'env.staging', 'env.staging.services', 'env.staging.durable_objects.bindings']);
  const tables = new Map([['', [{}]]]);
  let current = tables.get('')[0];
  for (const line of readFileSync(new URL('../wrangler.toml', import.meta.url), 'utf8').split(/\r?\n/)) {
    const text = line.trim();
    if (!text || text.startsWith('#')) continue;
    const header = text.match(/^\[\[?([\w.]+)\]\]?$/);
    if (header) {
      current = null;
      if (names.has(header[1])) {
        current = {};
        if (!tables.has(header[1])) tables.set(header[1], []);
        tables.get(header[1]).push(current);
      }
      continue;
    }
    if (!current) continue;
    const field = text.match(/^(\w+)\s*=\s*(.+)$/);
    assert.ok(field, `unsupported binding field: ${text}`);
    assert.equal(Object.hasOwn(current, field[1]), false, `duplicate binding field: ${field[1]}`);
    current[field[1]] = JSON.parse(field[2]);
  }
  return tables;
}

function servicesFor(tables, section) {
  const bindings = tables.get(section) ?? [];
  assert.equal(new Set(bindings.map(binding => binding.binding)).size, bindings.length, 'duplicate service binding');
  return Object.fromEntries(bindings.map(({ binding, ...target }) => [binding, target]));
}

test('production retains the default authority and uses the dedicated deletion entrypoint', () => {
  const tables = bindingTables();
  const bindings = servicesFor(tables, 'services');
  assert.deepEqual(bindings.IDENTITY_AUTHORITY, { service: 'padiem-control-plane-identity' });
  assert.deepEqual(bindings.COMMON_LOGIN_DELETION_RECORD, {
    service: 'padiem-control-plane-identity', entrypoint: 'CommonLoginDeletionRecord',
  });
  assert.equal(tables.get('')[0].name, 'padiem-auth');
  assert.equal(tables.get('')[0].workers_dev, false);
});

test('staging explicitly binds both authority entrypoints to its own service', () => {
  const tables = bindingTables();
  assert.equal(tables.get('env.staging')?.[0].name, 'padiem-auth-staging');
  assert.deepEqual(servicesFor(tables, 'env.staging.services'), {
    IDENTITY_AUTHORITY: { service: 'padiem-control-plane-identity-staging' },
    COMMON_LOGIN_DELETION_RECORD: {
      service: 'padiem-control-plane-identity-staging', entrypoint: 'CommonLoginDeletionRecord',
    },
  });
});

test('staging retains its own auth state binding and the inherited SQLite migration', () => {
  const tables = bindingTables();
  const ownState = [{ name: 'AUTH_STATE', class_name: 'AuthStateObject' }];
  assert.deepEqual(tables.get('durable_objects.bindings'), ownState);
  assert.deepEqual(tables.get('env.staging.durable_objects.bindings'), ownState);
  assert.ok(tables.get('migrations')?.some(migration => migration.new_sqlite_classes?.includes('AuthStateObject')));
});
