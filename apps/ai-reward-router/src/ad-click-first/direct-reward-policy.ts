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
  readonly rewardedVideoPath: 'SUPPORTED' | 'UNCONFIRMED' | 'NOT_APPLICABLE';
  readonly realWorldUserReward: 'ALLOWED_OR_SUPPORTED' | 'CONDITIONALLY_ALLOWED' | 'PROHIBITED' | 'UNCONFIRMED';
  readonly koreaSupply: 'UNCONFIRMED' | 'NOT_REQUIRED_FOR_POLICY_DECISION';
  readonly activateInAdClickP0: boolean;
  readonly reason: string;
}

export const DIRECT_REWARD_PROVIDER_POLICIES: readonly DirectRewardProviderPolicy[] = Object.freeze([
  Object.freeze({
    providerId: 'SRC-AYET',
    state: 'CANDIDATE_ONBOARDING_REQUIRED',
    webPath: 'SUPPORTED',
    rewardedVideoPath: 'SUPPORTED',
    realWorldUserReward: 'ALLOWED_OR_SUPPORTED',
    koreaSupply: 'UNCONFIRMED',
    activateInAdClickP0: false,
    reason: 'Official web Rewarded Video/Offerwall and reward callbacks are supported, and publisher terms explicitly allow real/non-virtual rewards. B64 still needs real publisher approval, placement/adslot, terms, credentials, ads.txt, consent, demand setup, Korea fill and live evidence before activation.',
  }),
  Object.freeze({
    providerId: 'ADSCEND_MEDIA',
    state: 'CANDIDATE_ONBOARDING_REQUIRED',
    webPath: 'SUPPORTED',
    rewardedVideoPath: 'SUPPORTED',
    realWorldUserReward: 'CONDITIONALLY_ALLOWED',
    koreaSupply: 'UNCONFIRMED',
    activateInAdClickP0: false,
    reason: 'Official website integration supports Offer Wall and standalone video/PixelPointTV; publisher guidance explicitly describes user rewards websites, Earn Gift Cards/Participate to Earn Cash language, and cash traffic on allowed offers. Each offer/reward model plus Korea video fill must still be cleared through publisher approval/account-manager terms before B64 activation.',
  }),
  Object.freeze({
    providerId: 'REVU',
    state: 'CANDIDATE_ONBOARDING_REQUIRED',
    webPath: 'SUPPORTED',
    rewardedVideoPath: 'UNCONFIRMED',
    realWorldUserReward: 'CONDITIONALLY_ALLOWED',
    koreaSupply: 'UNCONFIRMED',
    activateInAdClickP0: false,
    reason: 'Official current RevU materials describe web/desktop offerwall/API integration and distinguish GPT publishers whose users are paid real money from virtual-currency publishers. The standard integration docs still emphasize publisher rewards, so B64 must obtain publisher approval and explicit cash/GPT model clearance before activation. This is a low-friction offer-completion candidate, not yet an ad-view candidate.',
  }),
  Object.freeze({
    providerId: 'SRC-ADPOPCORN',
    state: 'CANDIDATE_MOBILE_PATH_ONLY',
    webPath: 'UNCONFIRMED',
    rewardedVideoPath: 'SUPPORTED',
    realWorldUserReward: 'ALLOWED_OR_SUPPORTED',
    koreaSupply: 'NOT_REQUIRED_FOR_POLICY_DECISION',
    activateInAdClickP0: false,
    reason: 'Official reward products include rewarded video/click rewards and external-value Naver Pay point rewards, but the currently reviewed integration path is mobile-centric and not yet a cleared B64 web path.',
  }),
  Object.freeze({
    providerId: 'SRC-TNK',
    state: 'CANDIDATE_MOBILE_PATH_ONLY',
    webPath: 'UNCONFIRMED',
    rewardedVideoPath: 'SUPPORTED',
    realWorldUserReward: 'ALLOWED_OR_SUPPORTED',
    koreaSupply: 'NOT_REQUIRED_FOR_POLICY_DECISION',
    activateInAdClickP0: false,
    reason: 'Official reward products include offerwall/rewarded video and KakaoPay point reward use cases, but the currently reviewed integration path is mobile SDK-centric and not yet a cleared B64 web path.',
  }),
  Object.freeze({
    providerId: 'SRC-ADISON',
    state: 'PENDING_EXPLICIT_REWARD_VALUE_CLEARANCE',
    webPath: 'UNCONFIRMED',
    rewardedVideoPath: 'UNCONFIRMED',
    realWorldUserReward: 'UNCONFIRMED',
    koreaSupply: 'NOT_REQUIRED_FOR_POLICY_DECISION',
    activateInAdClickP0: false,
    reason: 'Callback/HMAC capability is known, but B64 has not established an explicit web consumer path plus authority for external-value user rewards.',
  }),
  Object.freeze({
    providerId: 'GOOGLE_REWARDED_ADS',
    state: 'BLOCK_REAL_WORLD_REWARD',
    webPath: 'NOT_APPLICABLE',
    rewardedVideoPath: 'SUPPORTED',
    realWorldUserReward: 'PROHIBITED',
    koreaSupply: 'NOT_REQUIRED_FOR_POLICY_DECISION',
    activateInAdClickP0: false,
    reason: 'Provider rewarded-ad policy prohibits direct monetary items as rewards and restricts indirect rewards to the publisher platform; do not use this route for B64 direct user earnings.',
  }),
  Object.freeze({
    providerId: 'UNITY_TAPJOY_REWARDED',
    state: 'BLOCK_REAL_WORLD_REWARD',
    webPath: 'SUPPORTED',
    rewardedVideoPath: 'SUPPORTED',
    realWorldUserReward: 'PROHIBITED',
    koreaSupply: 'NOT_REQUIRED_FOR_POLICY_DECISION',
    activateInAdClickP0: false,
    reason: 'Web Offerwall capability exists, but rewarded inventory policy prohibits incentivizing ad views/actions with real-world rewards such as cash, gift cards, goods, services, vouchers or other things of value.',
  }),
  Object.freeze({
    providerId: 'ADGATE_MEDIA',
    state: 'PENDING_EXPLICIT_REWARD_VALUE_CLEARANCE',
    webPath: 'SUPPORTED',
    rewardedVideoPath: 'SUPPORTED',
    realWorldUserReward: 'UNCONFIRMED',
    koreaSupply: 'UNCONFIRMED',
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
