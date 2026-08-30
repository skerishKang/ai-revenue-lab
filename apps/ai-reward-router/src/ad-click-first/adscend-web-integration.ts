export const ADSCEND_VIDEO_CATEGORY_ID = 19 as const;
export const ADSCEND_CASH_INCENTIVE_ALLOWED_TRAFFIC = 3 as const;

export type AdscendAllowedTraffic = 0 | 1 | 2 | 3;

export interface AdscendOfferApiRecord {
  readonly offerId: number;
  readonly allowedTraffic: AdscendAllowedTraffic;
  readonly categoryIds: readonly number[];
  readonly previewUrl: string | null;
  readonly endDate: string | null;
  readonly conversionNotes: string | null;
}

export interface AdscendP0OfferAssessmentInput {
  readonly offer: AdscendOfferApiRecord;
  readonly koreaEligible: boolean;
  readonly webEligible: boolean;
  readonly accountManagerClearedForB64CashModel: boolean;
}

export type AdscendP0OfferSuppressionReason =
  | 'NOT_VIDEO_CATEGORY'
  | 'CASH_INCENTIVE_NOT_ALLOWED_FOR_OFFER'
  | 'KOREA_NOT_CONFIRMED'
  | 'WEB_NOT_CONFIRMED'
  | 'B64_CASH_MODEL_NOT_CLEARED'
  | 'OFFER_ENDED';

export interface AdscendP0OfferAssessment {
  readonly eligibleForP0InventoryTest: boolean;
  readonly reasons: readonly AdscendP0OfferSuppressionReason[];
}

function isEnded(endDate: string | null, now: Date): boolean {
  if (!endDate) return false;
  const timestamp = Date.parse(endDate);
  return Number.isFinite(timestamp) && timestamp <= now.getTime();
}

/**
 * This is an inventory-test filter, not consumer visibility authority.
 * Adscend's Offers API distinguishes offer-specific incentive permissions:
 * allowed_traffic=3 is the only state that explicitly permits points or cash incentives.
 */
export function assessAdscendP0VideoOffer(
  input: AdscendP0OfferAssessmentInput,
  now: Date = new Date(),
): AdscendP0OfferAssessment {
  const reasons: AdscendP0OfferSuppressionReason[] = [];
  if (!input.offer.categoryIds.includes(ADSCEND_VIDEO_CATEGORY_ID)) reasons.push('NOT_VIDEO_CATEGORY');
  if (input.offer.allowedTraffic !== ADSCEND_CASH_INCENTIVE_ALLOWED_TRAFFIC) reasons.push('CASH_INCENTIVE_NOT_ALLOWED_FOR_OFFER');
  if (!input.koreaEligible) reasons.push('KOREA_NOT_CONFIRMED');
  if (!input.webEligible) reasons.push('WEB_NOT_CONFIRMED');
  if (!input.accountManagerClearedForB64CashModel) reasons.push('B64_CASH_MODEL_NOT_CLEARED');
  if (isEnded(input.offer.endDate, now)) reasons.push('OFFER_ENDED');
  return Object.freeze({
    eligibleForP0InventoryTest: reasons.length === 0,
    reasons: Object.freeze(reasons),
  });
}

export interface AdscendWebVideoBrowserConfigInput {
  readonly publisherId: number;
  readonly offerWallProfileId: number;
  readonly externalUserId: string;
}

export interface AdscendWebVideoBrowserConfig {
  readonly iframeUrl: string;
  readonly categoryId: 19;
  readonly apiKeyExposedToBrowser: false;
}

function requirePositiveInteger(value: number, field: string): void {
  if (!Number.isInteger(value) || value <= 0) throw new Error(`${field} must be a positive integer`);
}

function requireExternalUserId(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 60 || !/^[A-Za-z0-9._:-]+$/.test(trimmed)) {
    throw new Error('externalUserId must be a stable opaque identifier up to 60 safe characters');
  }
  return trimmed;
}

/**
 * Creates a video-only website Offer Wall URL. Publisher API keys are intentionally
 * absent because Adscend API credentials belong server-side.
 */
export function buildAdscendWebVideoBrowserConfig(
  input: AdscendWebVideoBrowserConfigInput,
): AdscendWebVideoBrowserConfig {
  requirePositiveInteger(input.publisherId, 'publisherId');
  requirePositiveInteger(input.offerWallProfileId, 'offerWallProfileId');
  const externalUserId = requireExternalUserId(input.externalUserId);
  const url = new URL(
    `https://adscendmedia.com/adwall/publisher/${input.publisherId}/profile/${input.offerWallProfileId}`,
  );
  url.searchParams.set('subid1', externalUserId);
  url.searchParams.set('category_id', String(ADSCEND_VIDEO_CATEGORY_ID));
  return Object.freeze({
    iframeUrl: url.toString(),
    categoryId: ADSCEND_VIDEO_CATEGORY_ID,
    apiKeyExposedToBrowser: false as const,
  });
}

export const ADSCEND_P0_GO_LIVE_REQUIREMENTS = Object.freeze([
  'PUBLISHER_ACCOUNT_APPROVED',
  'B64_GPT_CASH_OR_EXTERNAL_VALUE_REWARD_MODEL_APPROVED',
  'WEBSITE_OFFERWALL_PROFILE_CREATED',
  'VIDEO_ONLY_CATEGORY_CONFIGURED',
  'UNIQUE_STATIC_USER_IDS_AVAILABLE',
  'SERVER_POSTBACK_CONFIGURED',
  'SECURE_HASH_ENABLED_AND_VERIFIED',
  'PUBLISHER_API_KEY_SERVER_SIDE_ONLY',
  'KOREA_VIDEO_INVENTORY_LIVE_TESTED',
  'ONLY_ALLOWED_TRAFFIC_3_OFFERS_ACCEPTED_FOR_CASH_REWARD',
  'EXTERNAL_REWARD_FULFILLMENT_READY_WITHOUT_B64_CASH_CUSTODY',
  'FRAUD_AND_DUPLICATE_CONTROLS_READY',
] as const);

export interface AdscendP0ReadinessInput {
  readonly publisherApproved: boolean;
  readonly cashRewardModelApproved: boolean;
  readonly offerWallProfileReady: boolean;
  readonly videoOnlyCategoryReady: boolean;
  readonly stableUserIdsReady: boolean;
  readonly serverPostbackReady: boolean;
  readonly secureHashVerified: boolean;
  readonly apiKeyServerSideOnly: boolean;
  readonly koreaVideoFillObserved: boolean;
  readonly offerLevelAllowedTrafficEnforced: boolean;
  readonly externalRewardFulfillmentReady: boolean;
  readonly b64CashCustodyEnabled: boolean;
  readonly fraudControlsReady: boolean;
}

export interface AdscendP0ReadinessResult {
  readonly readyForLiveAuthorizationReview: boolean;
  readonly missingRequirements: readonly string[];
}

export function assessAdscendP0Readiness(input: AdscendP0ReadinessInput): AdscendP0ReadinessResult {
  const missing: string[] = [];
  if (!input.publisherApproved) missing.push('PUBLISHER_ACCOUNT_APPROVED');
  if (!input.cashRewardModelApproved) missing.push('B64_GPT_CASH_OR_EXTERNAL_VALUE_REWARD_MODEL_APPROVED');
  if (!input.offerWallProfileReady) missing.push('WEBSITE_OFFERWALL_PROFILE_CREATED');
  if (!input.videoOnlyCategoryReady) missing.push('VIDEO_ONLY_CATEGORY_CONFIGURED');
  if (!input.stableUserIdsReady) missing.push('UNIQUE_STATIC_USER_IDS_AVAILABLE');
  if (!input.serverPostbackReady) missing.push('SERVER_POSTBACK_CONFIGURED');
  if (!input.secureHashVerified) missing.push('SECURE_HASH_ENABLED_AND_VERIFIED');
  if (!input.apiKeyServerSideOnly) missing.push('PUBLISHER_API_KEY_SERVER_SIDE_ONLY');
  if (!input.koreaVideoFillObserved) missing.push('KOREA_VIDEO_INVENTORY_LIVE_TESTED');
  if (!input.offerLevelAllowedTrafficEnforced) missing.push('ONLY_ALLOWED_TRAFFIC_3_OFFERS_ACCEPTED_FOR_CASH_REWARD');
  if (!input.externalRewardFulfillmentReady || input.b64CashCustodyEnabled) {
    missing.push('EXTERNAL_REWARD_FULFILLMENT_READY_WITHOUT_B64_CASH_CUSTODY');
  }
  if (!input.fraudControlsReady) missing.push('FRAUD_AND_DUPLICATE_CONTROLS_READY');
  return Object.freeze({
    readyForLiveAuthorizationReview: missing.length === 0,
    missingRequirements: Object.freeze(missing),
  });
}
