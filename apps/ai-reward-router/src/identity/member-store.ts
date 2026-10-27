import type { D1DatabaseLike } from '../income-pipeline/d1-user-income-repository.js';
import { isB64GoogleSubject } from './google.js';
import { isB64MemberId, isB64SessionId } from './session.js';

/**
 * B64's own members and sessions (issue #987, owner boundary decision
 * 2026-10-27: B64 is an independent business, so its accounts live here and
 * nowhere else).
 *
 * Same house rules the income repository already follows, reused rather than
 * reinvented:
 * - the constructor fails closed on a missing or unusable binding;
 * - every statement is prepared with bound parameters, so input can never
 *   change statement shape;
 * - a D1 result reporting `success: false` is a storage failure, never ignored;
 * - DDL is never executed at runtime — `migrations/d1/0002_b64_member.sql` and
 *   `0003_b64_google_identity.sql` are applied by the dispatch-only B64 D1
 *   provision gate;
 * - no global delete: a member's rows are addressed by that member, and the
 *   existing income data in `b64_user_income` is untouched by this schema.
 */

export interface B64Member {
  readonly id: string;
  readonly email: string;
  readonly passwordHash: string;
  readonly createdAt: string;
}

export interface B64Session {
  readonly id: string;
  readonly memberId: string;
  readonly expiresAt: string;
  readonly revokedAt: string | null;
}

/**
 * One Google account linked to one B64 member (`0003_b64_google_identity.sql`).
 * The subject, not the email, is what resolves a returning visitor.
 */
export interface B64GoogleMember {
  readonly googleSub: string;
  readonly memberId: string;
  readonly email: string;
  readonly linkedAt: string;
}

/** The Google side of a member, read back for authority decisions. */
export interface B64GoogleLink {
  readonly googleSub: string;
  readonly email: string;
}

export class B64MemberStorageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'B64MemberStorageError';
  }
}

export class B64MemberExistsError extends Error {
  constructor() {
    super('a member is already registered for this address');
    this.name = 'B64MemberExistsError';
  }
}

export interface B64MemberStore {
  createMember(member: B64Member): Promise<void>;
  findByEmail(email: string): Promise<B64Member | null>;
  createSession(session: B64Session): Promise<void>;
  /** Returns the session only while it is unrevoked; expiry is the caller's check. */
  findLiveSession(sessionId: string): Promise<B64Session | null>;
  revokeSession(sessionId: string): Promise<void>;
  /** The member a Google subject was linked to, or null. Email is never consulted here. */
  findMemberIdByGoogleSub(googleSub: string): Promise<string | null>;
  linkGoogleMember(record: B64GoogleMember): Promise<void>;
  /**
   * The Google side of one member, for the authority decision that asks "was
   * this account proven by Google, and to which address". A member who only
   * ever used a password has no row and returns null.
   */
  findGoogleLinkByMemberId(memberId: string): Promise<B64GoogleLink | null>;
}

function assertMemberShape(member: B64Member): void {
  if (!isB64MemberId(member.id)) throw new B64MemberStorageError('member id is not a B64 member id');
  if (!member.email || !member.passwordHash || !member.createdAt) {
    throw new B64MemberStorageError('member rows require email, password hash and created_at');
  }
}

function assertSessionShape(session: B64Session): void {
  if (!isB64SessionId(session.id)) throw new B64MemberStorageError('session id is not a B64 session id');
  if (!isB64MemberId(session.memberId)) throw new B64MemberStorageError('session belongs to a B64 member');
  if (!session.expiresAt) throw new B64MemberStorageError('session rows require expires_at');
}

function assertGoogleShape(record: B64GoogleMember): void {
  if (!isB64GoogleSubject(record.googleSub)) throw new B64MemberStorageError('google subject is not a usable identity');
  if (!isB64MemberId(record.memberId)) throw new B64MemberStorageError('google link requires a B64 member id');
  if (!record.email || !record.linkedAt) {
    throw new B64MemberStorageError('google link requires email and linked_at');
  }
}

interface MemberRow {
  id: string;
  email: string;
  password_hash: string;
  created_at: string;
}

interface GoogleRow {
  member_id: string;
}

interface GoogleLinkRow {
  google_sub: string;
  email: string;
}

interface SessionRow {
  id: string;
  member_id: string;
  expires_at: string;
  revoked_at: string | null;
}

export class D1B64MemberStore implements B64MemberStore {
  constructor(private readonly db: D1DatabaseLike) {
    if (!db || typeof db.prepare !== 'function') {
      throw new B64MemberStorageError('B64 member storage unavailable: D1 binding is not configured');
    }
  }

  async createMember(member: B64Member): Promise<void> {
    assertMemberShape(member);
    if (await this.findByEmail(member.email)) throw new B64MemberExistsError();
    const result = await this.db
      .prepare('INSERT INTO b64_member (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)')
      .bind(member.id, member.email, member.passwordHash, member.createdAt)
      .run();
    if (result.success === false) throw new B64MemberStorageError('member create failed');
  }

  async findByEmail(email: string): Promise<B64Member | null> {
    const row = await this.db
      .prepare('SELECT id, email, password_hash, created_at FROM b64_member WHERE email = ?')
      .bind(email)
      .first<MemberRow>();
    if (!row) return null;
    return Object.freeze({ id: row.id, email: row.email, passwordHash: row.password_hash, createdAt: row.created_at });
  }

  async createSession(session: B64Session): Promise<void> {
    assertSessionShape(session);
    const result = await this.db
      .prepare('INSERT INTO b64_session (id, member_id, expires_at, revoked_at) VALUES (?, ?, ?, ?)')
      .bind(session.id, session.memberId, session.expiresAt, session.revokedAt)
      .run();
    if (result.success === false) throw new B64MemberStorageError('session create failed');
  }

  async findLiveSession(sessionId: string): Promise<B64Session | null> {
    const row = await this.db
      .prepare('SELECT id, member_id, expires_at, revoked_at FROM b64_session WHERE id = ? AND revoked_at IS NULL')
      .bind(sessionId)
      .first<SessionRow>();
    if (!row) return null;
    return Object.freeze({ id: row.id, memberId: row.member_id, expiresAt: row.expires_at, revokedAt: row.revoked_at });
  }

  /**
   * Scoped to one session id. A session row that is already revoked is left
   * alone so a repeated logout cannot rewrite history, and no statement here
   * can touch another member's sessions.
   */
  async revokeSession(sessionId: string): Promise<void> {
    const result = await this.db
      .prepare('UPDATE b64_session SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL')
      .bind(new Date().toISOString(), sessionId)
      .run();
    if (result.success === false) throw new B64MemberStorageError('session revoke failed');
  }

  async findMemberIdByGoogleSub(googleSub: string): Promise<string | null> {
    if (!isB64GoogleSubject(googleSub)) throw new B64MemberStorageError('google subject is not a usable identity');
    const row = await this.db
      .prepare('SELECT member_id FROM b64_member_google WHERE google_sub = ?')
      .bind(googleSub)
      .first<GoogleRow>();
    if (!row) return null;
    if (!isB64MemberId(row.member_id)) throw new B64MemberStorageError('google link points at a non-B64 member');
    return row.member_id;
  }

  /** The subject is the key: re-linking a subject that already exists fails. */
  async linkGoogleMember(record: B64GoogleMember): Promise<void> {
    assertGoogleShape(record);
    const result = await this.db
      .prepare('INSERT INTO b64_member_google (google_sub, member_id, email, linked_at) VALUES (?, ?, ?, ?)')
      .bind(record.googleSub, record.memberId, record.email, record.linkedAt)
      .run();
    if (result.success === false) throw new B64MemberStorageError('google link failed');
  }

  async findGoogleLinkByMemberId(memberId: string): Promise<B64GoogleLink | null> {
    if (!isB64MemberId(memberId)) throw new B64MemberStorageError('member id is not a B64 member id');
    const row = await this.db
      .prepare('SELECT google_sub, email FROM b64_member_google WHERE member_id = ?')
      .bind(memberId)
      .first<GoogleLinkRow>();
    if (!row) return null;
    if (!isB64GoogleSubject(row.google_sub) || !row.email) {
      throw new B64MemberStorageError('google link row is not a usable identity');
    }
    return Object.freeze({ googleSub: row.google_sub, email: row.email });
  }
}

/** Fail-closed stand-in for a deployment without the D1 binding. */
export class UnboundB64MemberStore implements B64MemberStore {
  constructor(private readonly bindingName: string) {}

  private fail(): never {
    throw new B64MemberStorageError(
      `B64 member storage unavailable: D1 binding ${this.bindingName} is not configured on this deployment`,
    );
  }

  async createMember(_member: B64Member): Promise<void> { this.fail(); }
  async findByEmail(_email: string): Promise<B64Member | null> { this.fail(); }
  async createSession(_session: B64Session): Promise<void> { this.fail(); }
  async findLiveSession(_sessionId: string): Promise<B64Session | null> { this.fail(); }
  async revokeSession(_sessionId: string): Promise<void> { this.fail(); }
  async findMemberIdByGoogleSub(_googleSub: string): Promise<string | null> { this.fail(); }
  async linkGoogleMember(_record: B64GoogleMember): Promise<void> { this.fail(); }
  async findGoogleLinkByMemberId(_memberId: string): Promise<B64GoogleLink | null> { this.fail(); }
}

/** Test/local-prototype store. Never injected as a production fallback. */
export class InMemoryB64MemberStore implements B64MemberStore {
  private readonly membersByEmail = new Map<string, B64Member>();
  private readonly sessions = new Map<string, B64Session>();
  private readonly membersByGoogleSub = new Map<string, string>();
  private readonly linksByMemberId = new Map<string, B64GoogleLink>();

  async createMember(member: B64Member): Promise<void> {
    assertMemberShape(member);
    if (this.membersByEmail.has(member.email)) throw new B64MemberExistsError();
    this.membersByEmail.set(member.email, Object.freeze({ ...member }));
  }

  async findByEmail(email: string): Promise<B64Member | null> {
    return this.membersByEmail.get(email) ?? null;
  }

  async createSession(session: B64Session): Promise<void> {
    assertSessionShape(session);
    this.sessions.set(session.id, Object.freeze({ ...session }));
  }

  async findLiveSession(sessionId: string): Promise<B64Session | null> {
    const session = this.sessions.get(sessionId);
    if (!session || session.revokedAt !== null) return null;
    return session;
  }

  async revokeSession(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session || session.revokedAt !== null) return;
    this.sessions.set(sessionId, Object.freeze({ ...session, revokedAt: new Date().toISOString() }));
  }

  async findMemberIdByGoogleSub(googleSub: string): Promise<string | null> {
    if (!isB64GoogleSubject(googleSub)) throw new B64MemberStorageError('google subject is not a usable identity');
    return this.membersByGoogleSub.get(googleSub) ?? null;
  }

  async linkGoogleMember(record: B64GoogleMember): Promise<void> {
    assertGoogleShape(record);
    if (this.membersByGoogleSub.has(record.googleSub)) throw new B64MemberStorageError('google link failed');
    this.membersByGoogleSub.set(record.googleSub, record.memberId);
    this.linksByMemberId.set(record.memberId, Object.freeze({ googleSub: record.googleSub, email: record.email }));
  }

  async findGoogleLinkByMemberId(memberId: string): Promise<B64GoogleLink | null> {
    if (!isB64MemberId(memberId)) throw new B64MemberStorageError('member id is not a B64 member id');
    return this.linksByMemberId.get(memberId) ?? null;
  }
}
