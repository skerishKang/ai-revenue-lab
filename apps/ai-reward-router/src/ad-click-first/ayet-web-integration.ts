import { AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS } from './ayet-rewarded-video.js';

export interface AyetWebRewardedVideoRuntimeInput {
  readonly publisherAccountApproved: boolean;
  readonly placementId: number | null;
  readonly adslotName: string | null;
  readonly adsTxtPublished: boolean;
  readonly cmpConsentFlowReady: boolean;
  readonly demandSetupFinalized: boolean;
  readonly publisherApiKeyAvailableServerSide: boolean;
}

export interface AyetPublicClientConfig {
  readonly sdkUrl: 'https://cdn.ayet.io/offerwall/js/ayetvideosdk.min.js';
  readonly placementId: number;
  readonly adslotName: string;
  readonly externalIdentifier: string;
  readonly optionalParameter: string | null;
}

export const AYET_REWARDED_VIDEO_SDK_URL = 'https://cdn.ayet.io/offerwall/js/ayetvideosdk.min.js' as const;

export function evaluateAyetWebRewardedVideoGoLive(input: AyetWebRewardedVideoRuntimeInput) {
  const missing: string[] = [];
  if (!input.publisherAccountApproved) missing.push('PUBLISHER_ACCOUNT_APPROVED');
  if (!Number.isInteger(input.placementId) || (input.placementId ?? 0) <= 0) missing.push('WEBSITE_PLACEMENT_CREATED');
  if (!input.adslotName?.trim()) missing.push('REWARDED_VIDEO_ADSLOT_CREATED');
  if (!input.adsTxtPublished) missing.push('ADS_TXT_PUBLISHED');
  if (!input.cmpConsentFlowReady) missing.push('CMP_CONSENT_FLOW_READY');
  if (!input.demandSetupFinalized) missing.push('DEMAND_SETUP_FINALIZED_WITH_ACCOUNT_MANAGER');
  if (!input.publisherApiKeyAvailableServerSide) missing.push('PUBLISHER_API_KEY_SERVER_SIDE_ONLY');

  return Object.freeze({
    ready: missing.length === 0,
    missing: Object.freeze(missing),
    required: AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS,
  });
}

export function createAyetPublicClientConfig(input: {
  readonly placementId: number;
  readonly adslotName: string;
  readonly externalIdentifier: string;
  readonly optionalParameter?: string | null;
}): AyetPublicClientConfig {
  if (!Number.isInteger(input.placementId) || input.placementId <= 0) throw new Error('placementId must be a positive integer');
  const adslotName = input.adslotName.trim();
  if (!adslotName) throw new Error('adslotName is required');
  const externalIdentifier = input.externalIdentifier.trim();
  if (externalIdentifier.length < 3 || externalIdentifier.length > 128) throw new Error('externalIdentifier must be 3-128 characters');
  const optionalParameter = input.optionalParameter?.trim() || null;
  if (optionalParameter && optionalParameter.length > 32) throw new Error('optionalParameter must be <= 32 characters');

  return Object.freeze({
    sdkUrl: AYET_REWARDED_VIDEO_SDK_URL,
    placementId: input.placementId,
    adslotName,
    externalIdentifier,
    optionalParameter,
  });
}
