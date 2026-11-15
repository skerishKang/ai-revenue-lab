// P7 account-number issuance for the common login. No provider subject, email or
// canonical account number is ever written to the shadow log.
export function plainRpc(value) {
  if (value instanceof Map) return Object.fromEntries([...value].map(([k, v]) => [k, plainRpc(v)]));
  if (Array.isArray(value)) return value.map(plainRpc);
  if (value && typeof value === 'object' && typeof value.toJs === 'function') return plainRpc(value.toJs({ dict_converter: Object.fromEntries }));
  return value;
}

export function accountProvisioningMode(value) {
  return value === 'shadow' || value === 'on' ? value : 'off';
}

export function accountProposal() {
  // Same public shape as the existing authority: sub_ + 16 random bytes (32 hex).
  return 'sub_' + [...crypto.getRandomValues(new Uint8Array(16))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
}

export async function registerAccountProposal({ authority, authProvider, providerSubject, proposal }) {
  if (!authority || typeof authority.resolve_or_create_identity_subject !== 'function' ||
      !/^sub_[A-Za-z0-9_-]+$/.test(proposal ?? '')) throw new Error('identity subject registration failed');
  const result = plainRpc(await authority.resolve_or_create_identity_subject({
    auth_provider: authProvider,
    provider_subject: providerSubject,
    proposed_canonical_subject_id: proposal,
  }));
  if (result?.ok !== true || !/^sub_[A-Za-z0-9_-]+$/.test(result.canonical_subject_id ?? '') ||
      !Number.isSafeInteger(result.account_created_at) || result.account_created_at < 0 ||
      typeof result.already_registered !== 'boolean') {
    throw new Error('identity subject registration failed');
  }
  return {
    accountId: result.canonical_subject_id,
    accountCreatedAt: result.account_created_at,
    alreadyRegistered: result.already_registered,
  };
}

export function logProvisioningShadow(productId, provider, known, outcome) {
  const product = typeof productId === 'string' && /^[a-z0-9-]{1,40}$/.test(productId) ? productId : 'other';
  const method = provider === 'password' ? 'password' : 'google';
  const allowed = new Set(['match', 'mismatch', 'registration_rejected']);
  console.log(JSON.stringify({
    auth_stage: 'identity_provisioning_shadow', product, method, known: Boolean(known),
    outcome: allowed.has(outcome) ? outcome : 'registration_rejected',
  }));
}
