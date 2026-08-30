export const DIRECT_REWARD_POLICY_STATES = [
  'CANDIDATE_ONBOARDING_REQUIRED',
  'CANDIDATE_MOBILE_PATH_ONLY',
  'PENDING_EXPLICIT_REWARD_VALUE_CLEARANCE',
  'BLOCK_REAL_WORLD_REWARD',
] as const;
export type DirectRewardPolicyState = (typeof DIRECT_REWARD_POLICY_STATES)[number];

export interface DirectRewardProviderPolicy {
  readonly providerId: string;
  readonly state: DirectRewardPolicyState;
  readonly webPath: 'SUPPORTED' | 'UNCONFIRMED' | 'NOT_APPLICABLE';
  readonly realWorldUserReward: 'ALLOWED_OR_SUPPORTED' | 'PROHIBITED' | 'UNCONFIRMED';
  readonly activateInAdClickP0: boolean;
  readonly reason: string;
}

export const DIRECT_REWARD_PROVIDER_POLICIES: readonly DirectRewardProviderPolicy[] = Object.freeze([
  Object.freeze({
    providerId: 'SRC-AYET',
    state: 'CANDIDATE_ONBOARDING_REQUIRED',
    webPath: 'SUPPORTED',
    realWorldUserReward: 'ALLOWED_OR_SUPPORTED',
    activateInAdClickP0: false,
    reason: 'Official web Rewarded Video/Offerwall and reward callbacks are supported; B64 still needs real publisher approval, placement/adslot, terms, credentials, ads.txt, consent, demand setup and live evidence before activation.',
  }),
  Object.freeze({
    providerId: 'SRC-ADPOPCORN',
    state: 'CANDIDATE_MOBILE_PATH_ONLY',
    webPath: 'UNCONFIRMED',
    realWorldUserReward: 'ALLOWED_OR_SUPPORTED',
    activateInAdClickP0: false,
    reason: 'Official reward products include rewarded video/click rewards and external-value Naver Pay point rewards, but the currently reviewed integration path is mobile-centric and not yet a cleared B64 web path.',
  }),
  Object.freeze({
    providerId: 'SRC-TNK',
    state: 'CANDIDATE_MOBILE_PATH_ONLY',
    webPath: 'UNCONFIRMED',
    realWorldUserReward: 'ALLOWED_OR_SUPPORTED',
    activateInAdClickP0: false,
    reason: 'Official reward products include offerwall/rewarded video and KakaoPay point reward use cases, but the currently reviewed integration path is mobile SDK-centric and not yet a cleared B64 web path.',
  }),
  Object.freeze({
    providerId: 'SRC-ADISON',
    state: 'PENDING_EXPLICIT_REWARD_VALUE_CLEARANCE',
    webPath: 'UNCONFIRMED',
    realWorldUserReward: 'UNCONFIRMED',
    activateInAdClickP0: false,
    reason: 'Callback/HMAC capability is known, but B64 has not established an explicit web consumer path plus authority for external-value user rewards.',
  }),
  Object.freeze({
    providerId: 'GOOGLE_REWARDED_ADS',
    state: 'BLOCK_REAL_WORLD_REWARD',
    webPath: 'NOT_APPLICABLE',
    realWorldUserReward: 'PROHIBITED',
    activateInAdClickP0: false,
    reason: 'Provider rewarded-ad policy prohibits direct monetary or other disallowed real-world rewards; do not use this route for B64 user earnings.',
  }),
  Object.freeze({
    providerId: 'UNITY_TAPJOY_REWARDED',
    state: 'BLOCK_REAL_WORLD_REWARD',
    webPath: 'SUPPORTED',
    realWorldUserReward: 'PROHIBITED',
    activateInAdClickP0: false,
    reason: 'Web Offerwall capability exists, but rewarded inventory policy prohibits incentivizing ad views/actions with real-world rewards such as cash, gift cards, goods, services, vouchers or other things of value.',
  }),
  Object.freeze({
    providerId: 'ADGATE_MEDIA',
    state: 'PENDING_EXPLICIT_REWARD_VALUE_CLEARANCE',
    webPath: 'SUPPORTED',
    realWorldUserReward: 'UNCONFIRMED',
    activateInAdClickP0: false,
    reason: 'Web Offerwall/API support exists, but reviewed public materials emphasize virtual currency/credits and do not yet establish B64 authority to pay users external-value rewards.',
  }),
]);

export function directRewardPolicyByProvider(providerId: string): DirectRewardProviderPolicy {
  const policy = DIRECT_REWARD_PROVIDER_POLICIES.find((item) => item.providerId === providerId);
  if (!policy) throw new Error(`Unknown direct reward provider policy: ${providerId}`);
  return policy;
}

export function canActivateDirectRewardProvider(providerId: string): boolean {
  return directRewardPolicyByProvider(providerId).activateInAdClickP0;
}
