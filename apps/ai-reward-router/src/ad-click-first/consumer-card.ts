import { AD_CLICK_P0_ACTION_KINDS, type AdClickP0ActionKind } from './index.js';

export type AdClickSupplyLifecycle = 'LIVE' | 'EXPIRING' | 'STALE' | 'ENDED' | 'BROKEN';
export type AdClickProviderActivation = 'LIVE_AUTHORIZED' | 'BLOCKED' | 'PENDING_ONBOARDING';
export type AdClickCertainty = 'GUARANTEED' | 'CONDITIONAL';

export interface AdClickConsumerCandidate {
  readonly id: string;
  readonly sourceId: string;
  readonly title: string;
  readonly actionKind: AdClickP0ActionKind;
  readonly rewardAmount: number | null;
  readonly rewardUnit: string | null;
  readonly certainty: AdClickCertainty;
  readonly conditionSummary: string;
  readonly estimatedActiveSeconds: number | null;
  readonly canonicalDestinationUrl: string | null;
  readonly lastVerifiedAt: string;
  readonly lifecycle: AdClickSupplyLifecycle;
  readonly sourcePolicyCleared: boolean;
  readonly providerActivation: AdClickProviderActivation;
}

export type AdClickSurfaceSuppressionReason =
  | 'SOURCE_POLICY_NOT_CLEARED'
  | 'PROVIDER_NOT_LIVE_AUTHORIZED'
  | 'NOT_CURRENTLY_LIVE'
  | 'REWARD_NOT_CONFIRMED'
  | 'ACTION_NOT_LOW_FRICTION'
  | 'DESTINATION_NOT_SAFE_HTTPS'
  | 'FRESHNESS_INVALID';

export interface AdClickConsumerCard {
  readonly id: string;
  readonly sourceId: string;
  readonly tier: 'AD_CLICK';
  readonly title: string;
  readonly actionKind: AdClickP0ActionKind;
  readonly rewardLabel: string;
  readonly certainty: AdClickCertainty;
  readonly conditionSummary: string;
  readonly estimatedActiveSeconds: number;
  readonly canonicalDestinationUrl: string;
  readonly lastVerifiedAt: string;
}

export interface AdClickSurfaceAssessment {
  readonly visible: boolean;
  readonly reasons: readonly AdClickSurfaceSuppressionReason[];
  readonly card: AdClickConsumerCard | null;
}

function isSafeHttpsUrl(value: string | null): value is string {
  if (!value) return false;
  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

export function assessAdClickConsumerCandidate(candidate: AdClickConsumerCandidate): AdClickSurfaceAssessment {
  const reasons: AdClickSurfaceSuppressionReason[] = [];
  if (!candidate.sourcePolicyCleared) reasons.push('SOURCE_POLICY_NOT_CLEARED');
  if (candidate.providerActivation !== 'LIVE_AUTHORIZED') reasons.push('PROVIDER_NOT_LIVE_AUTHORIZED');
  if (candidate.lifecycle !== 'LIVE' && candidate.lifecycle !== 'EXPIRING') reasons.push('NOT_CURRENTLY_LIVE');
  if (!Number.isFinite(candidate.rewardAmount) || (candidate.rewardAmount ?? 0) <= 0 || !candidate.rewardUnit?.trim()) reasons.push('REWARD_NOT_CONFIRMED');
  if (!AD_CLICK_P0_ACTION_KINDS.includes(candidate.actionKind) || !Number.isFinite(candidate.estimatedActiveSeconds) || (candidate.estimatedActiveSeconds ?? 0) <= 0 || (candidate.estimatedActiveSeconds ?? 0) > 300) {
    reasons.push('ACTION_NOT_LOW_FRICTION');
  }
  if (!isSafeHttpsUrl(candidate.canonicalDestinationUrl)) reasons.push('DESTINATION_NOT_SAFE_HTTPS');
  if (!Number.isFinite(Date.parse(candidate.lastVerifiedAt))) reasons.push('FRESHNESS_INVALID');

  if (reasons.length > 0) {
    return Object.freeze({ visible: false, reasons: Object.freeze(reasons), card: null });
  }

  const rewardAmount = candidate.rewardAmount as number;
  const rewardUnit = candidate.rewardUnit as string;
  const estimatedActiveSeconds = candidate.estimatedActiveSeconds as number;
  const canonicalDestinationUrl = candidate.canonicalDestinationUrl as string;
  return Object.freeze({
    visible: true,
    reasons: Object.freeze([]),
    card: Object.freeze({
      id: candidate.id,
      sourceId: candidate.sourceId,
      tier: 'AD_CLICK' as const,
      title: candidate.title,
      actionKind: candidate.actionKind,
      rewardLabel: `${rewardAmount} ${rewardUnit}`,
      certainty: candidate.certainty,
      conditionSummary: candidate.conditionSummary,
      estimatedActiveSeconds,
      canonicalDestinationUrl,
      lastVerifiedAt: candidate.lastVerifiedAt,
    }),
  });
}

export function buildDefaultAdClickCards(candidates: readonly AdClickConsumerCandidate[]): readonly AdClickConsumerCard[] {
  return Object.freeze(
    candidates.flatMap((candidate) => {
      const assessment = assessAdClickConsumerCandidate(candidate);
      return assessment.card ? [assessment.card] : [];
    }),
  );
}
