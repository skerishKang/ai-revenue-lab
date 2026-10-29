// Storage primitive only. Callers must authenticate the client and hash tokens first.
// One Durable Object per session serializes code consumption and refresh rotation.
export class AuthState {
  constructor(state) {
    this.storage = state.storage;
    this.sql = this.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS client_assertions (jti TEXT PRIMARY KEY, expires INTEGER NOT NULL)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS login_requests (
      state_digest TEXT PRIMARY KEY, browser_digest TEXT NOT NULL, client TEXT NOT NULL,
      redirect TEXT NOT NULL, service_state TEXT NOT NULL, service_challenge TEXT NOT NULL,
      google_nonce TEXT NOT NULL, google_verifier TEXT NOT NULL, expires INTEGER NOT NULL,
      consumed INTEGER NOT NULL DEFAULT 0
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS codes (
      digest TEXT PRIMARY KEY, client TEXT NOT NULL, redirect TEXT NOT NULL,
      challenge TEXT NOT NULL, subject TEXT NOT NULL, expires INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY, client TEXT NOT NULL, subject TEXT NOT NULL,
      expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
    )`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS refresh_tokens (
      digest TEXT PRIMARY KEY, session_id TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0
    )`);
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

  createCode({ digest, client, redirect, challenge, subject, expires }) {
    this.sql.exec('INSERT INTO codes(digest,client,redirect,challenge,subject,expires) VALUES(?,?,?,?,?,?)', digest, client, redirect, challenge, subject, expires);
  }

  consumeCode({ digest, client, redirect, challenge, now }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE codes SET consumed=1 WHERE digest=? AND client=? AND redirect=? AND challenge=? AND consumed=0 AND expires>? RETURNING digest', digest, client, redirect, challenge, now).toArray();
      return rows.length === 1;
    });
  }

  createSession({ id, client, subject, expires, digest }) {
    return this.storage.transactionSync(() => {
      this.sql.exec('INSERT INTO sessions(id,client,subject,expires) VALUES(?,?,?,?)', id, client, subject, expires);
      this.sql.exec('INSERT INTO refresh_tokens(digest,session_id) VALUES(?,?)', digest, id);
    });
  }

  // The code and session live in the same object: if creating either session row
  // fails, consuming the code must roll back too. Authentication and PKCE
  // verification happen before calling this method.
  exchangeCode({ codeDigest, client, redirect, challenge, now, id, expires, refreshDigest }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE codes SET consumed=1 WHERE digest=? AND client=? AND redirect=? AND challenge=? AND consumed=0 AND expires>? RETURNING subject', codeDigest, client, redirect, challenge, now).toArray();
      if (rows.length !== 1) return false;
      this.sql.exec('INSERT INTO sessions(id,client,subject,expires) VALUES(?,?,?,?)', id, client, rows[0].subject, expires);
      this.sql.exec('INSERT INTO refresh_tokens(digest,session_id) VALUES(?,?)', refreshDigest, id);
      return { subject: rows[0].subject };
    });
  }

  rotate({ id, client, digest, replacement, now }) {
    return this.storage.transactionSync(() => {
      const session = this.sql.exec('SELECT * FROM sessions WHERE id=? AND client=?', id, client).toArray()[0];
      if (!session || session.revoked || session.expires <= now) return { ok: false };
      const token = this.sql.exec('SELECT * FROM refresh_tokens WHERE session_id=? AND digest=?', id, digest).toArray()[0];
      if (!token) return { ok: false };
      if (token.used) {
        this.sql.exec('UPDATE sessions SET revoked=1 WHERE id=?', id);
        return { ok: false, replay: true };
      }
      this.sql.exec('UPDATE refresh_tokens SET used=1 WHERE session_id=? AND digest=?', id, digest);
      this.sql.exec('INSERT INTO refresh_tokens(digest,session_id) VALUES(?,?)', replacement, id);
      return { ok: true, subject: session.subject, expires: session.expires };
    });
  }

  revoke({ id, client, digest, now }) {
    return this.storage.transactionSync(() => {
      const rows = this.sql.exec('UPDATE sessions SET revoked=1 WHERE id=? AND client=? AND revoked=0 AND expires>? AND EXISTS (SELECT 1 FROM refresh_tokens WHERE session_id=? AND digest=? AND used=0) RETURNING id', id, client, now, id, digest).toArray();
      return rows.length === 1;
    });
  }
}
