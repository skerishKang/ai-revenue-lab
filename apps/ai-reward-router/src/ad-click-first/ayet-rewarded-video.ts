import { createHmac, timingSafeEqual } from 'node:crypto';

export interface AyetRewardedVideoClientCallback {
  readonly status: string;
  readonly rewarded: boolean;
  readonly externalIdentifier: string;
  readonly currency: number | string;
  readonly conversionId: string;
  readonly custom_1?: string;
  readonly custom_2?: string;
  readonly custom_3?: string;
  readonly custom_4?: string;
  readonly custom_5?: string;
  readonly signature: string;
}

export type AyetRewardedVideoDecision =
  | 'REJECT_INVALID_CALLBACK'
  | 'REJECT_INVALID_SIGNATURE'
  | 'REJECT_DUPLICATE_CONVERSION'
  | 'ACCEPT_PROVISIONAL_REWARD_EVENT';

export interface AyetRewardedVideoProcessingResult {
  readonly decision: AyetRewardedVideoDecision;
  readonly conversionId: string | null;
  readonly externalIdentifier: string | null;
  readonly currency: number | null;
  readonly settlementState: 'NONE' | 'PENDING_S2S_RECONCILIATION';
  readonly cashCustodyAction: 'NONE';
}

export const AYET_REWARDED_VIDEO_GO_LIVE_REQUIREMENTS = Object.freeze([
  'PUBLISHER_ACCOUNT_APPROVED',
  'WEBSITE_PLACEMENT_CREATED',
  'REWARDED_VIDEO_ADSLOT_CREATED',
  'ADS_TXT_PUBLISHED',
  'CMP_CONSENT_FLOW_READY',
  'DEMAND_SETUP_FINALIZED_WITH_ACCOUNT_MANAGER',
  'PUBLISHER_API_KEY_SERVER_SIDE_ONLY',
] as const);

function callbackPayload(details: Omit<AyetRewardedVideoClientCallback, 'signature'>): string {
  return [
    details.externalIdentifier,
    String(details.currency),
    details.conversionId,
    details.custom_1 ?? '',
    details.custom_2 ?? '',
    details.custom_3 ?? '',
    details.custom_4 ?? '',
    details.custom_5 ?? '',
  ].join('');
}

export function expectedAyetRewardedVideoSignature(
  details: Omit<AyetRewardedVideoClientCallback, 'signature'>,
  publisherApiKey: string,
): string {
  return createHmac('sha1', publisherApiKey).update(callbackPayload(details), 'utf8').digest('hex');
}

export function verifyAyetRewardedVideoClientCallback(
  details: AyetRewardedVideoClientCallback,
  publisherApiKey: string,
): boolean {
  if (!publisherApiKey || details.status !== 'success' || details.rewarded !== true) return false;
  if (!details.externalIdentifier || !details.conversionId) return false;
  const currency = Number(details.currency);
  if (!Number.isFinite(currency) || currency <= 0) return false;
  if (!/^[0-9a-f]{40}$/i.test(details.signature)) return false;

  const expected = expectedAyetRewardedVideoSignature(details, publisherApiKey);
  const actualBuffer = Buffer.from(details.signature.toLowerCase(), 'hex');
  const expectedBuffer = Buffer.from(expected, 'hex');
  return actualBuffer.length === expectedBuffer.length && timingSafeEqual(actualBuffer, expectedBuffer);
}

export function processAyetRewardedVideoClientCallback(
  details: AyetRewardedVideoClientCallback,
  publisherApiKey: string,
  seenConversionIds: ReadonlySet<string>,
): AyetRewardedVideoProcessingResult {
  const base = {
    conversionId: details.conversionId || null,
    externalIdentifier: details.externalIdentifier || null,
    currency: Number.isFinite(Number(details.currency)) ? Number(details.currency) : null,
    cashCustodyAction: 'NONE' as const,
  };

  if (details.status !== 'success' || details.rewarded !== true || !details.externalIdentifier || !details.conversionId || !Number.isFinite(Number(details.currency)) || Number(details.currency) <= 0) {
    return Object.freeze({ ...base, decision: 'REJECT_INVALID_CALLBACK' as const, settlementState: 'NONE' as const });
  }

  if (!verifyAyetRewardedVideoClientCallback(details, publisherApiKey)) {
    return Object.freeze({ ...base, decision: 'REJECT_INVALID_SIGNATURE' as const, settlementState: 'NONE' as const });
  }

  if (seenConversionIds.has(details.conversionId)) {
    return Object.freeze({ ...base, decision: 'REJECT_DUPLICATE_CONVERSION' as const, settlementState: 'NONE' as const });
  }

  return Object.freeze({
    ...base,
    decision: 'ACCEPT_PROVISIONAL_REWARD_EVENT' as const,
    settlementState: 'PENDING_S2S_RECONCILIATION' as const,
  });
}
