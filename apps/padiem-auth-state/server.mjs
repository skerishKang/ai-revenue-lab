import http from 'node:http';
import { AUTH_STATE_METHODS, AuthStateObject } from '../padiem-auth/worker.mjs';
import { emailRecoveryEnabled } from '../padiem-auth/email-recovery.mjs';
import { STATE_RPC_MAX_BODY_BYTES, STATE_RPC_TOLERANCE_SECONDS, verifyStateRpc } from '../padiem-auth/state-rpc.mjs';
import { openStateDatabase, sqliteAdapter, transactionSync } from './sqlite.mjs';

const namePattern = /^[A-Za-z0-9_-]{1,128}$/;
const jsonHeaders = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff', 'content-type': 'application/json' };
const epoch = () => Math.floor(Date.now() / 1000);

class RpcError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

async function readBody(request) {
  const declared = Number(request.headers['content-length'] || 0);
  if (!Number.isSafeInteger(declared) || declared < 0 || declared > STATE_RPC_MAX_BODY_BYTES) throw new RpcError(413, 'body_too_large');
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > STATE_RPC_MAX_BODY_BYTES) throw new RpcError(413, 'body_too_large');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function parsePayload(body) {
  let value;
  try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body)); } catch { throw new RpcError(400, 'invalid_json'); }
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join(',') !== 'args,name' || typeof value.name !== 'string' || !namePattern.test(value.name)) {
    throw new RpcError(400, 'invalid_payload');
  }
  return value;
}

function createObjectStore(database, env, fetcher) {
  const objects = new Map();
  const permanentNames = new Set(['google-account-registry', 'google-age-confirmation', 'password-login-gate', 'client-assertion-replay']);
  const objectLimit = 2048;
  const sql = sqliteAdapter(database);
  const evictIdle = () => {
    for (const [name, entry] of objects) {
      if (!permanentNames.has(name) && entry.active === 0) {
        objects.delete(name);
        return;
      }
    }
  };
  const stateFor = (name) => {
    const existing = objects.get(name);
    if (existing) {
      objects.delete(name);
      objects.set(name, existing);
      return existing.proxy;
    }
    if (objects.size >= objectLimit) evictIdle();
    let queue = Promise.resolve();
    const storage = {
      id: name,
      sql,
      transactionSync(operation) { return transactionSync(database, operation); },
      blockConcurrencyWhile(operation) {
        const next = queue.then(operation);
        queue = next.catch(() => {});
        return next;
      },
      // The service maintenance loop owns expiry alarms for the shared database.
      async setAlarm() {},
    };
    const state = { id: name, storage, blockConcurrencyWhile(operation) { return storage.blockConcurrencyWhile(operation); } };
    const object = new AuthStateObject(state, env, {
      recoveryFetcher: fetcher,
      recoveryStateFor: stateFor,
      deletedAccountCleanup: async ({ accountIdHash }) => ({ state: 'deleted', accountIdHash }),
    });
    const entry = { active: 0, proxy: null };
    entry.proxy = new Proxy(object, {
      get(target, property, receiver) {
        const value = Reflect.get(target, property, receiver);
        if (typeof value !== 'function' || property === 'constructor') return value;
        return async (...args) => {
          entry.active++;
          try {
            target._ensureSchemaFor(property);
            return await value.apply(target, args);
          } finally {
            entry.active--;
          }
        };
      },
    });
    objects.set(name, entry);
    return entry.proxy;
  };
  return { stateFor, cacheSize: () => objects.size };
}

function createNonceStore(database, now) {
  database.exec('CREATE TABLE IF NOT EXISTS auth_state_nonces (nonce TEXT PRIMARY KEY, expires INTEGER NOT NULL)');
  return (nonce, at) => transactionSync(database, () => {
    database.prepare('DELETE FROM auth_state_nonces WHERE expires<=?').run(now());
    const result = database.prepare('INSERT INTO auth_state_nonces(nonce,expires) VALUES(?,?) ON CONFLICT DO NOTHING').run(nonce, at + STATE_RPC_TOLERANCE_SECONDS + 1);
    return result.changes === 1;
  });
}

function createMaintenance(database) {
  return () => transactionSync(database, () => {
    const now = epoch();
    const day = Math.floor(now / 86400);
    const hour = Math.floor(now / 3600);
    const statements = [
      'DELETE FROM auth_state_nonces WHERE expires<=?',
      'DELETE FROM client_assertions WHERE expires<=?',
      'DELETE FROM login_requests WHERE expires<=?',
      'DELETE FROM age_confirmations WHERE expires<=?',
      'DELETE FROM password_attempts WHERE expires<=?',
      'DELETE FROM codes WHERE expires<=?',
      'DELETE FROM code_profiles WHERE expires<=?',
      'DELETE FROM auth_session_index WHERE expires<=?',
      'DELETE FROM refresh_tokens WHERE session_id IN (SELECT id FROM sessions WHERE expires<=?)',
      'DELETE FROM sessions WHERE expires<=?',
      'DELETE FROM account_deletion_locks WHERE expires<=?',
      'DELETE FROM account_deletion_audit WHERE deleted_at<=? AND account_id_hash NOT IN (SELECT account_id_hash FROM pending_chat_account_deletions)',
      'DELETE FROM email_confirmation_tokens WHERE expires<=?',
      "DELETE FROM email_confirmation_budget WHERE (scope='all' AND bucket<?) OR (scope<>'all' AND bucket<?)",
      'DELETE FROM login_failure_budget WHERE day<?',
    ];
    const params = [
      [now], [now], [now], [now], [now], [now], [now], [now], [now], [now], [now],
      [now - 365 * 24 * 60 * 60], [now], [day, hour], [day],
    ];
    const tables = new Set(database.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(row => row.name));
    for (let index = 0; index < statements.length; index++) {
      const table = statements[index].match(/^DELETE FROM ([A-Za-z0-9_]+)/)[1];
      if (tables.has(table)) database.prepare(statements[index]).run(...params[index]);
    }
  });
}

export function createStateService({ database = openStateDatabase(':memory:'), secret, env = {}, fetcher = fetch, now = epoch } = {}) {
  if (typeof secret !== 'string' || new TextEncoder().encode(secret).length < 32) throw new Error('state_secret_required');
  const { stateFor, cacheSize } = createObjectStore(database, env, fetcher);
  const claimNonce = createNonceStore(database, now);
  const maintenance = createMaintenance(database);

  const handle = async (request) => {
    const url = new URL(request.url, 'http://state.invalid');
    const method = url.pathname.startsWith('/rpc/') ? url.pathname.slice(5) : '';
    if (request.method !== 'POST' || !AUTH_STATE_METHODS.has(method)) return Response.json({ error: 'not_found' }, { status: 404, headers: jsonHeaders });
    if (request.headers['content-type']?.split(';')[0].trim().toLowerCase() !== 'application/json') {
      return Response.json({ error: 'unauthorized' }, { status: 401, headers: jsonHeaders });
    }
    const body = await readBody(request);
    const verified = await verifyStateRpc({
      secret, method: request.method, path: url.pathname, body,
      at: request.headers['x-padiem-auth-at'], nonce: request.headers['x-padiem-auth-nonce'],
      proof: request.headers['x-padiem-auth-proof'], now: now(),
    });
    if (!verified) return Response.json({ error: 'unauthorized' }, { status: 401, headers: jsonHeaders });
    if (!claimNonce(verified.nonce, verified.at)) return Response.json({ error: 'request_replayed' }, { status: 409, headers: jsonHeaders });
    if (['emailRecoveryCandidate', 'completeEmailRecovery'].includes(method) && !emailRecoveryEnabled(env.PADIEM_AUTH_EMAIL_RECOVERY_ENABLED)) {
      return Response.json({ error: 'not_found' }, { status: 404, headers: jsonHeaders });
    }
    if (['passwordEmailConfirmed', 'reserveEmailConfirmation', 'recordEmailConfirmationToken', 'completeEmailConfirmation'].includes(method) && !emailRecoveryEnabled(env.PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED)) {
      return Response.json({ error: 'not_found' }, { status: 404, headers: jsonHeaders });
    }
    const payload = parsePayload(body);
    try {
      const value = await stateFor(payload.name)[method](payload.args);
      return Response.json({ value: value ?? null }, { headers: jsonHeaders });
    } catch {
      console.error(JSON.stringify({ auth_stage: 'state_rpc_failed', method }));
      return Response.json({ error: 'state_failure' }, { status: 500, headers: jsonHeaders });
    }
  };

  const server = http.createServer((request, response) => {
    handle(request).then(async output => {
      response.writeHead(output.status, Object.fromEntries(output.headers));
      response.end(Buffer.from(await output.arrayBuffer()));
    }).catch(error => {
      const status = error instanceof RpcError ? error.status : 500;
      const code = error instanceof RpcError ? error.code : 'state_failure';
      if (!(error instanceof RpcError)) console.error(JSON.stringify({ auth_stage: 'state_http_failed' }));
      response.writeHead(status, jsonHeaders);
      response.end(JSON.stringify({ error: code }));
    });
  });

  return { server, stateFor, cacheSize, database, maintenance };
}
