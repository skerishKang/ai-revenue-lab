// Profile disclosure is opt-in per client; never infer permissions from a name.
const FIELDS = new Set(['email', 'email_verified', 'name', 'picture']);

export function profileClaimAllowlist(client) {
  const fields = client?.profile_claims;
  if (fields === undefined) return [];
  if (!Array.isArray(fields) || fields.length !== FIELDS.size ||
      new Set(fields).size !== fields.length || fields.some(field => !FIELDS.has(field))) {
    throw new Error('invalid profile allowlist');
  }
  return [...fields];
}

export function verifiedProfile(claims, allowlist) {
  if (!allowlist.length) return null;
  if (!claims || typeof claims.email !== 'string' || !claims.email.trim() ||
      claims.email.length > 320 || claims.email_verified !== true ||
      (claims.name != null && typeof claims.name !== 'string') ||
      (claims.picture != null && typeof claims.picture !== 'string')) {
    throw new Error('invalid verified profile');
  }
  const profile = { email: claims.email, email_verified: true,
    name: (claims.name || '').slice(0, 160), picture: (claims.picture || '').slice(0, 1000) };
  return Object.fromEntries(allowlist.map(field => [field, profile[field]]));
}
