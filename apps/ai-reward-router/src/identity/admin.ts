import type { B64MemberStore } from './member-store.js';
import { isB64MemberId } from './session.js';

/**
 * B64's operator authority (issue #6001).
 *
 * This is the repository's existing administrator rule, ported rather than
 * reinvented — `apps/padiem-chat/app/b66_member_admin.py::is_google_admin`
 * decides an admin by the address the identity provider proved, never by a
 * client-supplied flag, and refuses a password account the same authority. The
 * B64 translation keeps all three of those properties and changes only the
 * store it reads: B64's own `b64_member_google` link, in B64's own D1. No Chat
 * cookie, no Chat user table, no second identity system.
 *
 * The address itself is server configuration (`B64_ADMIN_EMAIL`) and is never
 * committed or logged. With it unset, nobody is an administrator — an absent
 * allowlist is a closed door, not an open one.
 */

export const B64_ADMIN_EMAIL_ENV = 'B64_ADMIN_EMAIL';

function normalizeEmail(value: string): string {
  return value.trim().toLowerCase();
}

export function isB64AdminConfigured(adminEmail: string | undefined): boolean {
  return typeof adminEmail === 'string' && adminEmail.trim().length > 0;
}

/**
 * True only when this member's account was created by a Google login whose
 * verified address equals the configured administrator address. A storage
 * failure is thrown, not swallowed: "could not check" must never answer as
 * "not an admin" on one path and "is an admin" on another.
 */
export async function isB64SuperAdmin(options: {
  readonly adminEmail: string | undefined;
  readonly members: B64MemberStore;
  readonly memberId: string | null;
}): Promise<boolean> {
  const configured = normalizeEmail(options.adminEmail ?? '');
  if (!configured) return false;
  if (options.memberId === null || !isB64MemberId(options.memberId)) return false;

  const link = await options.members.findGoogleLinkByMemberId(options.memberId);
  if (link === null) return false;
  if (!link.googleSub.trim() || link.googleSub.startsWith('password:')) return false;
  return normalizeEmail(link.email) === configured;
}
