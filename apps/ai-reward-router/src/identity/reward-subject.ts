/**
 * The B64 identifier a reward provider echoes back (issue #987).
 *
 * A provider callback arrives with no session cookie and no browser, so it
 * cannot be trusted with a member id. B64 hands the provider this signed
 * subject instead, and only this subject resolves to a member. A provider that
 * replays, edits or guesses the value gets a signature failure rather than
 * another person's account.
 *
 * It is signed with `B64_SESSION_SECRET` under its own purpose string. That is
 * not credential sharing: `hmac.ts` derives `key = HMAC(secret, purpose)` first,
 * so a session token, an OAuth state and a reward subject each verify only
 * under their own purpose. One owner-minted key stays the deployment surface.
 *
 * Length is bounded because the provider contract caps `externalIdentifier` at
 * 3-128 characters (`ayet-web-integration.ts`).
 */

import { readB64Token, signB64Token } from './hmac.js';
import { isB64MemberId } from './session.js';

export const B64_REWARD_SUBJECT_PURPOSE = 'b64-reward/ayet-subject/v1';
export const B64_REWARD_SUBJECT_MAX_AGE_SECONDS = 60 * 60 * 24 * 180;
export const B64_REWARD_SUBJECT_MAX_CHARS = 128;

export async function mintB64RewardSubject(options: {
  readonly signingSecret: string;
  readonly memberId: string;
  readonly nowSeconds?: number;
}): Promise<string> {
  if (!options.signingSecret) throw new Error('a signing secret is required to mint a reward subject');
  if (!isB64MemberId(options.memberId)) throw new Error('member id is not a B64 member id');
  const nowSeconds = options.nowSeconds ?? Math.floor(Date.now() / 1000);
  const token = await signB64Token(options.signingSecret, B64_REWARD_SUBJECT_PURPOSE, {
    v: 1,
    mid: options.memberId,
    exp: nowSeconds + B64_REWARD_SUBJECT_MAX_AGE_SECONDS,
  });
  if (token.length > B64_REWARD_SUBJECT_MAX_CHARS) {
    throw new Error(`reward subject exceeds the provider limit of ${B64_REWARD_SUBJECT_MAX_CHARS} characters`);
  }
  return token;
}

/** The member a subject was issued to, or null for anything not signed here. */
export async function readB64RewardSubject(
  token: string | null | undefined,
  signingSecret: string | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<string | null> {
  if (!token || !signingSecret || token.length > B64_REWARD_SUBJECT_MAX_CHARS) return null;
  const claims = await readB64Token(signingSecret, B64_REWARD_SUBJECT_PURPOSE, token, nowSeconds);
  if (!claims) return null;
  const memberId = claims['mid'];
  return isB64MemberId(memberId) ? memberId : null;
}
