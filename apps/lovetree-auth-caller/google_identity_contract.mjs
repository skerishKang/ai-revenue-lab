// Internal algorithm only: this helper does not authenticate a caller or expose an RPC.
// Call it only after a trusted server has verified the Google credential.
export async function googleProductUserId(verifiedSubject) {
  if (typeof verifiedSubject !== 'string' || !/^[\x21-\x7e]{1,255}$/.test(verifiedSubject)) throw new Error('invalid_verified_google_subject');
  const input = new TextEncoder().encode('google:' + verifiedSubject);
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', input));
  return 'usr_' + Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('').slice(0, 32);
}
