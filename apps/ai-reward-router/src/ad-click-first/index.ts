export const CONSUMER_SUPPLY_TIERS = [
  'AD_CLICK',
  'SURVEY',
  'MICROTASK',
  'SHORT_GIG',
  'EXTERNAL_JOB_SEARCH',
] as const;

export type ConsumerSupplyTier = (typeof CONSUMER_SUPPLY_TIERS)[number];
export type ConsumerSupplyVisibility = 'ENABLED' | 'HIDDEN_UNTIL_UNLOCK';

export const AD_CLICK_P0_ACTION_KINDS = [
  'AD_VIEW',
  'CLICK',
  'VISIT',
  'ATTENDANCE',
  'VERY_SHORT_FREE_ACTION',
] as const;
export type AdClickP0ActionKind = (typeof AD_CLICK_P0_ACTION_KINDS)[number];

export const AD_CLICK_FIRST_GATE = Object.freeze({
  issueNumber: 1112,
  status: 'IN_PROGRESS' as const,
  centralAcceptanceRequired: true,
  currentLaunchFocus: 'AD_VIEW_CLICK_VISIT_LOW_FRICTION_REWARD' as const,
});

export const CURRENT_CONSUMER_SUPPLY_VISIBILITY: Readonly<Record<ConsumerSupplyTier, ConsumerSupplyVisibility>> = Object.freeze({
  AD_CLICK: 'ENABLED',
  SURVEY: 'HIDDEN_UNTIL_UNLOCK',
  MICROTASK: 'HIDDEN_UNTIL_UNLOCK',
  SHORT_GIG: 'HIDDEN_UNTIL_UNLOCK',
  EXTERNAL_JOB_SEARCH: 'HIDDEN_UNTIL_UNLOCK',
});

export interface ConsumerSurfaceCandidate {
  readonly id: string;
  readonly tier: ConsumerSupplyTier;
}

export function isConsumerSupplyVisible(tier: ConsumerSupplyTier): boolean {
  return CURRENT_CONSUMER_SUPPLY_VISIBILITY[tier] === 'ENABLED';
}

export function filterDefaultConsumerSurface<T extends ConsumerSurfaceCandidate>(items: readonly T[]): readonly T[] {
  return Object.freeze(items.filter((item) => isConsumerSupplyVisible(item.tier)));
}

export const AD_CLICK_P0_SOURCE_STRATEGY = Object.freeze([
  Object.freeze({
    sourceId: 'SRC-AYET',
    rank: 1,
    readiness: 'PARTNER_ONBOARDING_REQUIRED' as const,
    webOfferwall: 'OFFICIAL_SUPPORTED' as const,
    webRewardedVideo: 'OFFICIAL_SUPPORTED' as const,
    incentiveMechanism: 'OFFICIAL_TERMS_ALLOW_VIRTUAL_OR_REAL_REWARDS' as const,
    conversionCallbacks: 'OFFICIAL_SUPPORTED' as const,
    liveB64Permission: 'NOT_YET_GRANTED' as const,
    activation: 'BLOCKED_UNTIL_ACCOUNT_ADSLOT_TERMS_AND_CREDENTIALS' as const,
  }),
  Object.freeze({
    sourceId: 'SRC-TNK',
    rank: 2,
    readiness: 'PARTNER_ONBOARDING_AND_WEB_FEASIBILITY_REVIEW_REQUIRED' as const,
    liveB64Permission: 'NOT_YET_GRANTED' as const,
    activation: 'BLOCKED' as const,
  }),
  Object.freeze({
    sourceId: 'SRC-ADISON',
    rank: 3,
    readiness: 'PARTNER_ONBOARDING_AND_WEB_TERMS_REVIEW_REQUIRED' as const,
    liveB64Permission: 'NOT_YET_GRANTED' as const,
    activation: 'BLOCKED' as const,
  }),
  Object.freeze({
    sourceId: 'SRC-ADPOPCORN',
    rank: 4,
    readiness: 'PARTNER_ONBOARDING_AND_WEB_FEASIBILITY_REVIEW_REQUIRED' as const,
    liveB64Permission: 'NOT_YET_GRANTED' as const,
    activation: 'BLOCKED' as const,
  }),
]);

export const EXCLUDED_DIRECT_CASH_REWARDED_AD_PATHS = Object.freeze([
  Object.freeze({
    provider: 'GOOGLE_REWARDED_ADS',
    reason: 'DIRECT_MONETARY_REWARDS_PROHIBITED_BY_PROVIDER_POLICY' as const,
  }),
]);

export * from './ayet-rewarded-video.js';
