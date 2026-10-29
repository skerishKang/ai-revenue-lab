// Storage primitive only. Callers must authenticate the client and hash tokens first.
// One Durable Object per session serializes code consumption and refresh rotation.
export class AuthState {
  constructor(state) {
    this.storage = state.storage;
    this.sql = this.storage.sql;
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

  revoke({ id, client }) {
    return this.storage.transactionSync(() => this.sql.exec('UPDATE sessions SET revoked=1 WHERE id=? AND client=?', id, client));
  }
}
