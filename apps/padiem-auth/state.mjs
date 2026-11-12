// Storage primitive only. Callers must authenticate the client and hash tokens first.
// One Durable Object per session serializes code consumption and refresh rotation.
export class AuthState {
  constructor(state) {
    this.storage = state.storage;
    this.sql = this.storage.sql;
    this.sql.exec('CREATE TABLE IF NOT EXISTS blocked_accounts (account_id TEXT PRIMARY KEY)');
    this.sql.exec(`CREATE TABLE IF NOT EXISTS google_accounts (
      fingerprint TEXT PRIMARY KEY, account_id TEXT NOT NULL UNIQUE,
      state TEXT NOT NULL CHECK(state IN ('active','blocked'))
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS client_assertions (jti TEXT PRIMARY KEY, expires INTEGER NOT NULL)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS login_requests (
      state_digest TEXT PRIMARY KEY, browser_digest TEXT NOT NULL, client TEXT NOT NULL,
      redirect TEXT NOT NULL, service_state TEXT NOT NULL, service_challenge TEXT NOT NULL,
      google_nonce TEXT NOT NULL, google_verifier TEXT NOT NULL, expires INTEGER NOT NULL,
      consumed INTEGER NOT NULL DEFAULT 0
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS password_attempts (
      state_digest TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires INTEGER NOT NULL
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS codes (
      digest TEXT PRIMARY KEY, client TEXT NOT NULL, redirect TEXT NOT NULL,
      challenge TEXT NOT NULL, subject TEXT NOT NULL, account_id TEXT NOT NULL, expires INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0, amr TEXT
    )`);
    this.sql.exec('CREATE TABLE IF NOT EXISTS code_profiles (digest TEXT PRIMARY KEY, ciphertext TEXT NOT NULL, expires INTEGER NOT NULL)');
    this.sql.exec(`CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY, client TEXT NOT NULL, subject TEXT NOT NULL, account_id TEXT NOT NULL,
      expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, amr TEXT
    )`);
    try { this.sql.exec('ALTER TABLE codes ADD COLUMN amr TEXT'); } catch { /* column already exists */ }
    try { this.sql.exec('ALTER TABLE sessions ADD COLUMN amr TEXT'); } catch { /* column already exists */ }
    this.sql.exec(`CREATE TABLE IF NOT EXISTS refresh_tokens (
      digest TEXT PRIMARY KEY, session_id TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
      grace_until INTEGER, grace_result TEXT, successor TEXT
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS auth_session_index (
      account_id TEXT NOT NULL, object_id TEXT NOT NULL, session_id TEXT NOT NULL,
      expires INTEGER NOT NULL, PRIMARY KEY(account_id, object_id, session_id)
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS account_deletion_locks (
      account_id TEXT PRIMARY KEY, lock_token TEXT NOT NULL, expires INTEGER NOT NULL
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS account_deletion_audit (
      account_id_hash TEXT PRIMARY KEY, deleted_at INTEGER NOT NULL
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS identity_deletion_tombstone (
      fingerprint TEXT PRIMARY KEY, deleted_at INTEGER NOT NULL
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS account_chat_users (
      account_id TEXT NOT NULL, product_user_id TEXT NOT NULL,
      PRIMARY KEY(account_id, product_user_id)
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS pending_chat_account_deletions (
      product_user_id TEXT PRIMARY KEY, account_id_hash TEXT NOT NULL, deleted_at INTEGER NOT NULL
    )`);
    // #7551: which Chat password credential an email identity was linked
    // with. The credential's creation time survives password change/reset and
    // changes only when the credential is created again, so a login that
    // presents a different one has not proven it owns the linked account.
    this.sql.exec(`CREATE TABLE IF NOT EXISTS password_credential_epochs (
      fingerprint TEXT PRIMARY KEY, epoch TEXT NOT NULL
    )`);
  }

  passwordCredentialEpoch({ fingerprint }) {
    return this.sql.exec('SELECT epoch FROM password_credential_epochs WHERE fingerprint=?', fingerprint).toArray()[0]?.epoch ?? null;
  }

  // Whether a password sign-in with this credential may be bound to the
  // account the email fingerprint already maps to (#7551).
  //  - signup: never onto a live account; the credential was just created, so
  //    nothing proves the person owns that account.
  //  - login: only with the credential the account was linked with.
  passwordBindingRefused({ fingerprint, epoch, register = false }) {
    const current = this.accountByFingerprint(fingerprint);
    if (!current) return false;
    if (register) return true;
    const known = this.passwordCredentialEpoch({ fingerprint });
    return known !== null && known !== epoch;
  }

  recordPasswordCredentialEpoch({ fingerprint, epoch }) {
    if (typeof fingerprint !== 'string' || typeof epoch !== 'string' || !epoch) return false;
    this.sql.exec(
      'INSERT INTO password_credential_epochs(fingerprint,epoch) VALUES(?,?) ON CONFLICT(fingerprint) DO NOTHING',
      fingerprint, epoch,
    );
    return true;
  }

  accountByFingerprint(fingerprint) {
    return this.sql.exec('SELECT account_id,state FROM google_accounts WHERE fingerprint=?', fingerprint).toArray()[0] || null;
  }

  accountById(accountId) {
    return this.sql.exec('SELECT account_id,state FROM google_accounts WHERE account_id=?', accountId).toArray()[0] || null;
  }

  putAccount({ fingerprint, accountId, productUserId, now = Math.floor(Date.now() / 1000) }) {
    return this.storage.transactionSync(() => {
      if (this.sql.exec('SELECT account_id FROM account_deletion_locks WHERE account_id=? AND expires>?', accountId, now).toArray().length) throw new Error('account_deletion_in_progress');
      if (this.sql.exec('SELECT account_id FROM blocked_accounts WHERE account_id=?', accountId).toArray().length) throw new Error('account_blocked');
      this.sql.exec("INSERT INTO google_accounts(fingerprint,account_id,state) VALUES(?,?,'active') ON CONFLICT(fingerprint) DO NOTHING", fingerprint, accountId);
      const record = this.accountByFingerprint(fingerprint);
      if (!record || record.account_id !== accountId || record.state !== 'active') throw new Error('identity_conflict');
      if (typeof productUserId === 'string' && /^usr_[A-Za-z0-9_-]{1,79}$/.test(productUserId)) {
        this.sql.exec('INSERT INTO account_chat_users(account_id,product_user_id) VALUES(?,?) ON CONFLICT DO NOTHING', accountId, productUserId);
      }
      return record;
    });
  }

  recordAccountChatUsers({ accountId, productUserIds }) {
    if (typeof accountId !== 'string' || !Array.isArray(productUserIds)) return 0;
    return this.storage.transactionSync(() => {
      let recorded = 0;
      for (const productUserId of productUserIds) {
        if (typeof productUserId === 'string' && /^usr_[A-Za-z0-9_-]{1,79}$/.test(productUserId)) {
          this.sql.exec('INSERT INTO account_chat_users(account_id,product_user_id) VALUES(?,?) ON CONFLICT DO NOTHING', accountId, productUserId);
          recorded++;
        }
      }
      return recorded;
    });
  }

  // #7078: password change/reset revokes the user's padiem-auth sessions.
  // account_chat_users is the only product-user -> canonical-account map here,
  // so a user with no shared login yet simply has nothing to revoke.
  accountIdsForChatUser({ productUserId }) {
    if (typeof productUserId !== 'string' || !/^usr_[A-Za-z0-9_-]{1,79}$/.test(productUserId)) return [];
    return this.sql.exec(
      'SELECT DISTINCT account_id FROM account_chat_users WHERE product_user_id=? ORDER BY account_id',
      productUserId,
    ).toArray().map((row) => row.account_id);
  }

  // A deleted identity must not be re-created by an automatic login. The
  // tombstone is keyed by the provider fingerprint (email/Google subject hash)
  // and is removed only by an explicit sign-up.
  identityIsDeleted({ fingerprint }) {
    return this.sql.exec('SELECT fingerprint FROM identity_deletion_tombstone WHERE fingerprint=?', fingerprint).toArray().length === 1;
  }

  clearIdentityDeletion({ fingerprint }) {
    this.sql.exec('DELETE FROM identity_deletion_tombstone WHERE fingerprint=?', fingerprint);
    return true;
  }

  pendingChatAccountDeletions({ accountIdHash } = {}) {
    if (typeof accountIdHash === 'string' && accountIdHash) {
      return this.sql.exec(
        'SELECT product_user_id FROM pending_chat_account_deletions WHERE account_id_hash=? ORDER BY product_user_id',
        accountIdHash
      ).toArray().map(row => row.product_user_id);
    }
    return this.sql.exec(
      'SELECT product_user_id FROM pending_chat_account_deletions ORDER BY deleted_at, product_user_id'
    ).toArray().map(row => row.product_user_id);
  }

  completeChatAccountDeletion({ productUserId }) {
    return this.sql.exec(
      'DELETE FROM pending_chat_account_deletions WHERE product_user_id=? RETURNING product_user_id',
      productUserId
    ).toArray().length === 1;
  }

  setAccountStatus({ accountId, blocked }) {
    if (!blocked) throw new Error('unblock is not implemented');
    return this.storage.transactionSync(() => {
      this.sql.exec('INSERT INTO blocked_accounts(account_id) VALUES(?) ON CONFLICT DO NOTHING', accountId);
      this.sql.exec("UPDATE google_accounts SET state='blocked' WHERE account_id=?", accountId);
      return true;
    });
  }

  claimAssertion({ key, expires, now }) {
    return this.storage.transactionSync(() => {
      this.sql.exec('DELETE FROM client_assertions WHERE expires<=?', now);
      const rows = this.sql.exec('INSERT INTO client_assertions(jti,expires) VALUES(?,?) ON CONFLICT DO NOTHING RETURNING jti', key, expires).toArray();
      return rows.length === 1;
    });
  }

  createLogin({ stateDigest, browserDigest, client, redirect, serviceState, serviceChallenge, googleNonce, googleVerifier, expires }) {
    this.sql.exec('INSERT INTO login_requests(state_digest,browser_digest,client,redirect,service_state,service_challenge,google_nonce,google_verifier,expires) VALUES(?,?,?,?,?,?,?,?,?)', stateDigest, browserDigest, client, redirect, serviceState, serviceChallenge, googleNonce, googleVerifier, expires);
  }

  consumeLogin({ stateDigest, browserDigest, now }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE login_requests SET consumed=1 WHERE state_digest=? AND browser_digest=? AND consumed=0 AND expires>? RETURNING client,redirect,service_state,service_challenge,google_nonce,google_verifier', stateDigest, browserDigest, now).toArray();
      return rows[0] || null;
    });
  }

  // One email-form attempt against a live login state. The attempt counter
  // bounds guessing against one rendered form without consuming the state, so
  // a mistyped first try can still succeed afterwards. A state that runs out
  // of attempts is consumed: it can no longer finish any leg, and the browser
  // restarts from /login with a fresh state.
  beginPasswordAttempt({ stateDigest, browserDigest, now, maxAttempts = 5 }) {
    return this.storage.transactionSync(() => {
      this.sql.exec('DELETE FROM password_attempts WHERE expires<=?', now);
      const rows = this.sql.exec('SELECT client,redirect,service_state,service_challenge FROM login_requests WHERE state_digest=? AND browser_digest=? AND consumed=0 AND expires>?', stateDigest, browserDigest, now).toArray();
      if (rows.length !== 1) return { ok: false, reason: 'invalid' };
      const counted = this.sql.exec('INSERT INTO password_attempts(state_digest,attempts,expires) VALUES(?,1,?) ON CONFLICT(state_digest) DO UPDATE SET attempts=attempts+1 RETURNING attempts', stateDigest, now + 600).toArray()[0];
      if (Number(counted?.attempts) > maxAttempts) {
        this.sql.exec('UPDATE login_requests SET consumed=1 WHERE state_digest=?', stateDigest);
        return { ok: false, reason: 'exhausted' };
      }
      return { ok: true, login: rows[0] };
    });
  }

  createCode({ digest, client, redirect, challenge, subject, accountId, expires, encryptedProfile, amr = null }) {
    return this.storage.transactionSync(() => {
      this.sql.exec('INSERT INTO codes(digest,client,redirect,challenge,subject,account_id,expires,amr) VALUES(?,?,?,?,?,?,?,?)', digest, client, redirect, challenge, subject, accountId, expires, amr);
      if (encryptedProfile) this.sql.exec('INSERT INTO code_profiles(digest,ciphertext,expires) VALUES(?,?,?)', digest, encryptedProfile, expires);
    });
  }

  clearExpiredProfiles(now) {
    this.sql.exec('DELETE FROM code_profiles WHERE expires<=?', now);
  }

  consumeCode({ digest, client, redirect, challenge, now }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE codes SET consumed=1 WHERE digest=? AND client=? AND redirect=? AND challenge=? AND consumed=0 AND expires>? RETURNING digest', digest, client, redirect, challenge, now).toArray();
      return rows.length === 1;
    });
  }

  createSession({ id, client, subject, accountId, expires, digest, amr = null }) {
    return this.storage.transactionSync(() => {
      this.sql.exec('INSERT INTO sessions(id,client,subject,account_id,expires,amr) VALUES(?,?,?,?,?,?)', id, client, subject, accountId, expires, amr);
      this.sql.exec('INSERT INTO refresh_tokens(digest,session_id) VALUES(?,?)', digest, id);
    });
  }

  // The code and session live in the same object: if creating either session row
  // fails, consuming the code must roll back too. Authentication and PKCE
  // verification happen before calling this method.
  exchangeCode({ codeDigest, client, redirect, challenge, now, id, expires, refreshDigest }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE codes SET consumed=1 WHERE digest=? AND client=? AND redirect=? AND challenge=? AND consumed=0 AND expires>? RETURNING subject,account_id,amr', codeDigest, client, redirect, challenge, now).toArray();
      if (rows.length !== 1) return false;
      const profile = this.sql.exec('DELETE FROM code_profiles WHERE digest=? AND expires>? RETURNING ciphertext', codeDigest, now).toArray()[0];
      this.sql.exec('DELETE FROM code_profiles WHERE digest=?', codeDigest);
      this.sql.exec('INSERT INTO sessions(id,client,subject,account_id,expires,amr) VALUES(?,?,?,?,?,?)', id, client, rows[0].subject, rows[0].account_id, expires, rows[0].amr ?? null);
      this.sql.exec('INSERT INTO refresh_tokens(digest,session_id) VALUES(?,?)', refreshDigest, id);
      const result = { subject: rows[0].subject, accountId: rows[0].account_id };
      if (rows[0].amr) result.amr = rows[0].amr;
      if (profile) result.encryptedProfile = profile.ciphertext;
      return result;
    });
  }

  inspectRefresh({ id, client, digest, now }) {
    return this.sql.exec('SELECT s.subject,s.account_id,s.expires,s.amr FROM sessions s JOIN refresh_tokens t ON t.session_id=s.id WHERE s.id=? AND s.client=? AND t.digest=? AND s.revoked=0 AND s.expires>?', id, client, digest, now).toArray()[0] || null;
  }

  rotate({ id, client, digest, replacement, encryptedResult, now }) {
    return this.storage.transactionSync(() => {
      const session = this.sql.exec('SELECT * FROM sessions WHERE id=? AND client=?', id, client).toArray()[0];
      if (!session || session.revoked || session.expires <= now) return { ok: false };
      const token = this.sql.exec('SELECT * FROM refresh_tokens WHERE session_id=? AND digest=?', id, digest).toArray()[0];
      if (!token) return { ok: false };
      if (token.used) {
        // A 30-second retry window covers concurrent browser tabs and a lost
        // response. Only the immediate predecessor qualifies, and only while
        // its successor remains unused; older replays still revoke the session.
        const next = this.sql.exec('SELECT used FROM refresh_tokens WHERE session_id=? AND digest=?', id, token.successor).toArray()[0];
        if (token.grace_until > now && token.grace_result && next && !next.used) {
          return { ok: true, encryptedResult: token.grace_result, accountId: session.account_id };
        }
        this.sql.exec('UPDATE sessions SET revoked=1 WHERE id=?', id);
        return { ok: false, replay: true };
      }
      if (!encryptedResult) throw new Error('encrypted response required');
      this.sql.exec('UPDATE refresh_tokens SET used=1,grace_until=?,grace_result=?,successor=? WHERE session_id=? AND digest=?', now + 30, encryptedResult, replacement, id, digest);
      this.sql.exec('INSERT INTO refresh_tokens(digest,session_id) VALUES(?,?)', replacement, id);
      return { ok: true, encryptedResult, accountId: session.account_id };
    });
  }

  forceRevokeForAccountDeletion({ id }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE sessions SET revoked=1 WHERE id=? AND revoked=0 RETURNING id', id).toArray();
      if (rows.length === 1) return true;
      return this.sql.exec('SELECT id FROM sessions WHERE id=? AND revoked=1', id).toArray().length === 1;
    });
  }

  indexAccountSession({ accountId, objectId, sessionId, expires, now }) {
    return this.storage.transactionSync(() => {
      const account = this.accountById(accountId);
      if (!account || account.state !== 'active') return false;
      if (this.sql.exec('SELECT account_id FROM account_deletion_locks WHERE account_id=? AND expires>?', accountId, now).toArray().length) return false;
      const rows = this.sql.exec(
        'INSERT INTO auth_session_index(account_id,object_id,session_id,expires) VALUES(?,?,?,?) ON CONFLICT DO NOTHING RETURNING session_id',
        accountId, objectId, sessionId, expires
      ).toArray();
      return rows.length === 1;
    });
  }

  beginAccountDeletion({ accountId, lockToken, now, leaseSeconds = 300 }) {
    return this.storage.transactionSync(() => {
      const blocked = this.sql.exec('SELECT account_id FROM blocked_accounts WHERE account_id=?', accountId).toArray().length > 0;
      if (blocked) return false;
      const current = this.sql.exec(
        'SELECT lock_token FROM account_deletion_locks WHERE account_id=? AND expires>?',
        accountId, now
      ).toArray();
      if (current.length) return current.length === 1 && current[0].lock_token === lockToken;
      this.sql.exec('DELETE FROM account_deletion_locks WHERE expires<=?', now);
      const rows = this.sql.exec(
        'INSERT INTO account_deletion_locks(account_id,lock_token,expires) VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET lock_token=excluded.lock_token,expires=excluded.expires WHERE account_deletion_locks.expires<=? RETURNING account_id',
        accountId, lockToken, now + leaseSeconds, now
      ).toArray();
      return rows.length === 1;
    });
  }

  indexedAccountSessions({ accountId }) {
    return this.sql.exec(
      'SELECT object_id,session_id FROM auth_session_index WHERE account_id=? ORDER BY object_id,session_id',
      accountId
    ).toArray();
  }

  releaseAccountDeletion({ accountId, lockToken }) {
    return this.sql.exec('DELETE FROM account_deletion_locks WHERE account_id=? AND lock_token=? RETURNING account_id', accountId, lockToken).toArray().length === 1;
  }

  finalizeAccountDeletion({ accountId, accountIdHash, lockToken, now }) {
    return this.storage.transactionSync(() => {
      if (!/^[a-f0-9]{64}$/.test(accountIdHash ?? '')) return false;
      const lock = this.sql.exec(
        'SELECT account_id FROM account_deletion_locks WHERE account_id=? AND lock_token=? AND expires>?',
        accountId, lockToken, now
      ).toArray();
      if (lock.length !== 1) {
        return this.sql.exec(
          'SELECT account_id_hash FROM account_deletion_audit WHERE account_id_hash=?',
          accountIdHash
        ).toArray().length === 1 && this.sql.exec(
          'SELECT product_user_id FROM pending_chat_account_deletions WHERE account_id_hash=?',
          accountIdHash
        ).toArray().length > 0;
      }
      this.sql.exec(
        'INSERT INTO identity_deletion_tombstone(fingerprint,deleted_at) SELECT fingerprint,? FROM google_accounts WHERE account_id=? ON CONFLICT(fingerprint) DO UPDATE SET deleted_at=excluded.deleted_at',
        now, accountId
      );
      this.sql.exec(
        'INSERT INTO pending_chat_account_deletions(product_user_id,account_id_hash,deleted_at) SELECT product_user_id,?,? FROM account_chat_users WHERE account_id=? ON CONFLICT(product_user_id) DO UPDATE SET account_id_hash=excluded.account_id_hash,deleted_at=excluded.deleted_at',
        accountIdHash, now, accountId
      );
      this.sql.exec('DELETE FROM account_chat_users WHERE account_id=?', accountId);
      this.sql.exec('DELETE FROM password_credential_epochs WHERE fingerprint IN (SELECT fingerprint FROM google_accounts WHERE account_id=?)', accountId);
      this.sql.exec('DELETE FROM google_accounts WHERE account_id=?', accountId);
      this.sql.exec('DELETE FROM auth_session_index WHERE account_id=?', accountId);
      this.sql.exec(
        'INSERT INTO account_deletion_audit(account_id_hash,deleted_at) VALUES(?,?) ON CONFLICT(account_id_hash) DO UPDATE SET deleted_at=excluded.deleted_at',
        accountIdHash, now
      );
      this.sql.exec('DELETE FROM account_deletion_locks WHERE account_id=? AND lock_token=?', accountId, lockToken);
      this.pruneAccountDeletionAudit({ now });
      return true;
    });
  }

  pruneAccountDeletionAudit({ now }) {
    return this.sql.exec('DELETE FROM account_deletion_audit WHERE deleted_at<=? RETURNING account_id_hash', now - 365 * 24 * 60 * 60).toArray().length;
  }

  nextAccountDeletionAuditExpiry() {
    const row = this.sql.exec('SELECT MIN(deleted_at) AS deleted_at FROM account_deletion_audit').toArray()[0];
    return Number.isInteger(row?.deleted_at) ? row.deleted_at + 365 * 24 * 60 * 60 : null;
  }

  revoke({ id, client, digest, now }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE sessions SET revoked=1 WHERE id=? AND client=? AND revoked=0 AND expires>? AND EXISTS (SELECT 1 FROM refresh_tokens WHERE session_id=? AND digest=? AND used=0) RETURNING id', id, client, now, id, digest).toArray();
      return rows.length === 1;
    });
  }
}

