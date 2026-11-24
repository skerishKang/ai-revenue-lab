import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { AuthStateObject } from '../worker.mjs';

function storage() {
  const db = new DatabaseSync(':memory:');
  let written = 0;
  return {
    db,
    get written() { return written; },
    sql: {
      exec(query, ...params) {
        const statement = db.prepare(query);
        if (statement.columns().length) {
          const rows = statement.all(...params);
          // RETURNING has already written before returning rows.
          if (/^\s*(?:INSERT|UPDATE|DELETE)\b/i.test(query)) written += rows.length;
          return { toArray: () => rows };
        }
        const result = statement.run(...params);
        written += result.changes;
        return { toArray: () => [] };
      },
    },
    transactionSync(fn) {
      db.exec('BEGIN');
      try {
        const result = fn();
        db.exec('COMMIT');
        return result;
      } catch (error) {
        db.exec('ROLLBACK');
        throw error;
      }
    },
  };
}

function schemaSize(storage) {
  return storage.db.prepare(
    "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
  ).get().n;
}

async function invoke(object, method, payload) {
  const reply = await object.fetch(new Request('https://internal/' + method, {
    method: 'POST',
    body: JSON.stringify(payload),
  }));
  assert.equal(reply.status, 200, method);
  return (await reply.json()).value;
}

test('fresh login DO creates only login tables and keeps one-use code/session guarantees', async () => {
  const oldStore = storage();
  new AuthState({ storage: oldStore });
  const baseline = schemaSize(oldStore);
  const currentStore = storage();
  const state = new AuthStateObject({ id: { toString: () => 'synthetic' }, storage: currentStore }, {});
  assert.equal(schemaSize(currentStore), 0);

  await invoke(state, 'createLogin', {
    stateDigest: 'synthetic-login-state', browserDigest: 'synthetic-browser',
    client: 'b62', redirect: 'synthetic-callback', serviceState: 'synthetic-service',
    serviceChallenge: 'synthetic-challenge', googleNonce: 'synthetic-nonce',
    googleVerifier: 'synthetic-verifier', expires: 1000,
  });
  const loginTables = schemaSize(currentStore);
  assert.equal(loginTables, 6);
  assert.ok(baseline > loginTables);
  console.log('baseline_tables=' + baseline + ' login_tables=' + loginTables + ' request_writes=' + currentStore.written);
  assert.equal(currentStore.written, 1);
  const consumed = await invoke(state, 'consumeLogin', {
    stateDigest: 'synthetic-login-state', browserDigest: 'synthetic-browser', now: 1,
  });
  assert.equal(consumed.client, 'b62');
  assert.equal(currentStore.written, 2);
  assert.equal(await invoke(state, 'consumeLogin', {
    stateDigest: 'synthetic-login-state', browserDigest: 'synthetic-browser', now: 1,
  }), null);
  assert.equal(currentStore.written, 2);
  assert.equal(schemaSize(currentStore), 6);
  // A later registry-only method completes the missing schema without damage.
  assert.equal(await invoke(state, 'accountById', 'nonexistent'), null);
  assert.equal(schemaSize(currentStore), baseline);
});

test('replay gate and password failure budget only initialize their own tables', async () => {
  const store = storage();
  const state = new AuthStateObject({ id: {}, storage: store }, {});
  assert.equal(await invoke(state, 'claimAssertion', { key: 'synthetic-jti', expires: 50, now: 1 }), true);
  assert.equal(schemaSize(store), 1);
  assert.equal(await invoke(state, 'claimAssertion', { key: 'synthetic-jti', expires: 50, now: 1 }), false);
  assert.equal(store.written, 1);
  assert.equal(await invoke(state, 'loginFailureBudget', { source: 'synthetic-source', day: 1, charge: false }), 0);
  assert.equal(schemaSize(store), 2);
  assert.equal(store.written, 1);
  assert.equal(await invoke(state, 'loginFailureBudget', { source: 'synthetic-source', day: 1, charge: true }), 1);
  assert.equal(store.written, 2);
  assert.equal(await invoke(state, 'loginFailureBudget', { source: 'synthetic-source', day: 1, charge: false }), 1);
  assert.equal(store.written, 2);
  assert.equal(await invoke(state, 'claimAssertion', { key: 'synthetic-jti', expires: 60, now: 51 }), true);
  assert.equal(store.written, 4); // one expired deletion plus one new claim
});

test('age gate retains atomic first-claim and cached result without unrelated schemas', async () => {
  const store = storage();
  const state = new AuthStateObject({ id: {}, storage: store }, {});
  await invoke(state, 'createAgeConfirmation', {
    handleDigest: 'synthetic-handle', browserDigest: 'synthetic-browser',
    payload: 'synthetic-payload', expires: 100, now: 1,
  });
  assert.equal(schemaSize(store), 1);
  assert.equal(await invoke(state, 'claimAgeConfirmation', {
    handleDigest: 'synthetic-handle', browserDigest: 'synthetic-browser', now: 2,
  }), 'synthetic-payload');
  assert.equal(await invoke(state, 'claimAgeConfirmation', {
    handleDigest: 'synthetic-handle', browserDigest: 'synthetic-browser', now: 2,
  }), null);
  await invoke(state, 'recordAgeConfirmationResult', {
    handleDigest: 'synthetic-handle', browserDigest: 'synthetic-browser',
    result: 'synthetic-result', expires: 100,
  });
  assert.deepEqual(await invoke(state, 'readAgeConfirmationResult', {
    handleDigest: 'synthetic-handle', browserDigest: 'synthetic-browser', now: 2,
  }), { claimed: true, result: 'synthetic-result' });
  assert.equal(schemaSize(store), 1);
});


test('code profile alarm after eviction prunes ciphertext without expanding schemas', async () => {
  const store = storage();
  let scheduled = 0;
  store.setAlarm = async millis => { scheduled = millis; };
  const state = new AuthStateObject({ id: {}, storage: store }, {});
  await invoke(state, 'createCode', {
    digest: 'synthetic-code', client: 'b62', redirect: 'synthetic-callback',
    challenge: 'synthetic-challenge', subject: 'synthetic-subject',
    accountId: 'synthetic-account', expires: 1,
    encryptedProfile: 'synthetic-private-profile',
  });
  assert.equal(schemaSize(store), 6);
  assert.equal(scheduled, 1000);
  assert.equal(store.db.prepare('SELECT COUNT(*) AS n FROM code_profiles').get().n, 1);
  const awakened = new AuthStateObject({ id: {}, storage: store }, {});
  await awakened.alarm();
  assert.equal(store.db.prepare('SELECT COUNT(*) AS n FROM code_profiles').get().n, 0);
  assert.equal(schemaSize(store), 6);
});
