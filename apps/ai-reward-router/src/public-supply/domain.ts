export const PUBLIC_OPPORTUNITY_CATEGORIES = ['SURVEY', 'USABILITY', 'MICROTASK', 'SHORT_GIG'] as const;
export type PublicOpportunityCategory = (typeof PUBLIC_OPPORTUNITY_CATEGORIES)[number];

export const PUBLIC_REWARD_BASES = ['HOURLY', 'PER_TASK', 'PER_ASSET', 'FIXED', 'UNCONFIRMED'] as const;
export type PublicRewardBasis = (typeof PUBLIC_REWARD_BASES)[number];

export const PUBLIC_TODAY_TIERS = ['IMMEDIATE', 'SCREENING_REQUIRED'] as const;
export type PublicTodayTier = (typeof PUBLIC_TODAY_TIERS)[number];

export type PublicOpportunityStatus = 'OPEN' | 'CLOSED';
export type KoreaStatus = 'CONFIRMED' | 'UNCONFIRMED';

export interface PublicReward {
  readonly displayValue: string;
  readonly currency: string | null;
  readonly basis: PublicRewardBasis;
  readonly confirmed: boolean;
}

export interface PublicOpportunity {
  readonly id: string;
  readonly sourceId: string;
  readonly vendor: string;
  readonly category: PublicOpportunityCategory;
  readonly titleKo: string;
  readonly titleEn: string | null;
  readonly country: string;
  readonly koreaStatus: KoreaStatus;
  readonly participationMethod: string;
  readonly reward: PublicReward;
  readonly payer: string;
  readonly qualifications: string;
  readonly applyUrl: string;
  readonly sourceUrl: string;
  readonly verifiedAt: string;
  readonly status: PublicOpportunityStatus;
  readonly todayTier: PublicTodayTier;
  /** Extra truthful nuance shown next to the tier label (e.g. rolling availability). */
  readonly tierNote: string | null;
  /** Action label on the outbound CTA (e.g. signup-only wording for registration listings). */
  readonly ctaLabel: string;
  /**
   * Deterministic user-value score (0-10), computed from verified attributes only:
   * base 4 + reward confirmed (+2) + IMMEDIATE tier (+2) + Korea confirmed (+2).
   * It never mixes in PADIEM monetization value.
   */
  readonly userValueScore: number;
  /** Public supply pays PADIEM nothing; monetization stays separated and zero. */
  readonly monetizationRole: 'NONE';
}

export type PublicOpportunityLoader = (
  request: Request,
) => Promise<readonly PublicOpportunity[]> | readonly PublicOpportunity[];

export interface PublicOpportunityCard {
  readonly id: string;
  readonly vendor: string;
  readonly category: PublicOpportunityCategory;
  readonly titleKo: string;
  readonly rewardLabel: string;
  readonly rewardBasisLabel: string;
  readonly rewardNote: string;
  readonly rewardConfirmed: boolean;
  readonly country: string;
  readonly koreaStatus: KoreaStatus;
  readonly koreaLabel: string;
  readonly todayTier: PublicTodayTier;
  readonly tierLabel: string;
  readonly tierNote: string | null;
  readonly ctaLabel: string;
  readonly userValueScore: number;
  readonly applyUrl: string;
  readonly verifiedAt: string;
}

export interface PublicOpportunityDetail {
  readonly card: PublicOpportunityCard;
  readonly participationMethod: string;
  readonly payer: string;
  readonly qualifications: string;
  readonly sourceUrl: string;
  readonly status: PublicOpportunityStatus;
  readonly monetizationRole: 'NONE';
}

export const PUBLIC_CATEGORY_LABELS: Readonly<Record<PublicOpportunityCategory, string>> = Object.freeze({
  SURVEY: '설문·리서치',
  USABILITY: '사용성 테스트',
  MICROTASK: 'AI 데이터·평가',
  SHORT_GIG: '온라인 프로젝트',
});

const REWARD_BASIS_LABELS: Readonly<Record<PublicRewardBasis, string>> = Object.freeze({
  HOURLY: '시간당',
  PER_TASK: '건당',
  PER_ASSET: '승인 에셋당',
  FIXED: '정액',
  UNCONFIRMED: '미확인',
});

const TIER_LABELS: Readonly<Record<PublicTodayTier, string>> = Object.freeze({
  IMMEDIATE: '참가자 등록 가능',
  SCREENING_REQUIRED: '신청·심사 후 참여',
});

/** Single-line reward display without doubled "미확인" wording. */
export function publicRewardNote(reward: PublicReward): string {
  if (reward.confirmed) return REWARD_BASIS_LABELS[reward.basis];
  if (reward.basis === 'UNCONFIRMED') return '미확인';
  return `${REWARD_BASIS_LABELS[reward.basis]} · 미확인`;
}

/** Korea eligibility is only claimed when officially confirmed. */
export function koreaEligibilityLabel(status: KoreaStatus): string {
  return status === 'CONFIRMED' ? '한국 참여 확인' : '한국 거주 자격 미확인';
}

export function computeUserValueScore(input: {
  rewardConfirmed: boolean;
  todayTier: PublicTodayTier;
  koreaConfirmed: boolean;
}): number {
  let score = 4;
  if (input.rewardConfirmed) score += 2;
  if (input.todayTier === 'IMMEDIATE') score += 2;
  if (input.koreaConfirmed) score += 2;
  return score;
}

function isHttpsUrl(value: string): boolean {
  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

/** Public opportunities older than this many days must be re-verified before active display. */
export const PUBLIC_OPPORTUNITY_MAX_AGE_DAYS = 7;

export function isPublicOpportunityDisplayable(
  opportunity: PublicOpportunity,
  now: Date = new Date(),
): boolean {
  if (opportunity.status !== 'OPEN') return false;
  if (!isHttpsUrl(opportunity.applyUrl)) return false;
  if (!isHttpsUrl(opportunity.sourceUrl)) return false;
  const verified = Date.parse(opportunity.verifiedAt);
  if (Number.isNaN(verified)) return false;
  const ageMs = now.getTime() - verified;
  if (ageMs > PUBLIC_OPPORTUNITY_MAX_AGE_DAYS * 24 * 60 * 60 * 1000) return false;
  return true;
}

/**
 * Two curated records for one offer are one opportunity. Curation adds records
 * by hand, so the same vendor/project can easily be entered twice; the consumer
 * screens would then show the same earning path as separate choices (#987
 * 중복 처리). Identity is the offer itself: vendor + Korean title + apply target.
 */
export function dedupePublicOpportunities(
  opportunities: readonly PublicOpportunity[],
): readonly PublicOpportunity[] {
  const seen = new Set<string>();
  const unique: PublicOpportunity[] = [];
  for (const opportunity of opportunities) {
    const key = [opportunity.vendor, opportunity.titleKo, opportunity.applyUrl]
      .join('|')
      .toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(opportunity);
  }
  return Object.freeze(unique);
}

/** The one verified-supply rule every consumer surface renders from. */
export function displayablePublicOpportunityCards(
  opportunities: readonly PublicOpportunity[],
): readonly PublicOpportunityCard[] {
  return Object.freeze(
    dedupePublicOpportunities(opportunities)
      .filter((opportunity) => isPublicOpportunityDisplayable(opportunity))
      .map(toPublicOpportunityCard),
  );
}

/**
 * How much verified supply is left, and when it stops showing. The 7-day
 * display window means a curated lane empties on a calendar date, so the
 * refresh owner needs the deadline before the consumer screens go blank
 * rather than after (#987 만료 처리).
 */
export interface PublicSupplyFreshness {
  readonly activeCount: number;
  readonly staleCount: number;
  readonly expiringWithinDays: number;
  readonly nextExpiryAt: string | null;
  readonly laneEmptyAt: string | null;
}

export const PUBLIC_SUPPLY_EXPIRY_WARNING_DAYS = 2;

export function assessPublicSupplyFreshness(
  opportunities: readonly PublicOpportunity[],
  now: Date = new Date(),
): PublicSupplyFreshness {
  const windowMs = PUBLIC_OPPORTUNITY_MAX_AGE_DAYS * 24 * 60 * 60 * 1000;
  let activeCount = 0;
  let staleCount = 0;
  let expiringWithinDays = 0;
  const expiryTimes: number[] = [];
  for (const opportunity of opportunities) {
    if (isPublicOpportunityDisplayable(opportunity, now)) {
      activeCount += 1;
      const expiresAt = Date.parse(opportunity.verifiedAt) + windowMs;
      expiryTimes.push(expiresAt);
      if (expiresAt - now.getTime() <= PUBLIC_SUPPLY_EXPIRY_WARNING_DAYS * 24 * 60 * 60 * 1000) {
        expiringWithinDays += 1;
      }
    } else {
      staleCount += 1;
    }
  }
  const sorted = expiryTimes.sort((a, b) => a - b);
  const next = sorted[0];
  const last = sorted[sorted.length - 1];
  return Object.freeze({
    activeCount,
    staleCount,
    expiringWithinDays,
    nextExpiryAt: next === undefined ? null : new Date(next).toISOString(),
    laneEmptyAt: last === undefined ? null : new Date(last).toISOString(),
  });
}

export function toPublicOpportunityCard(opportunity: PublicOpportunity): PublicOpportunityCard {
  const { reward } = opportunity;
  return Object.freeze({
    id: opportunity.id,
    vendor: opportunity.vendor,
    category: opportunity.category,
    titleKo: opportunity.titleKo,
    rewardLabel: reward.displayValue,
    rewardBasisLabel: REWARD_BASIS_LABELS[reward.basis],
    rewardNote: publicRewardNote(reward),
    rewardConfirmed: reward.confirmed,
    country: opportunity.country,
    koreaStatus: opportunity.koreaStatus,
    koreaLabel: koreaEligibilityLabel(opportunity.koreaStatus),
    todayTier: opportunity.todayTier,
    tierLabel: TIER_LABELS[opportunity.todayTier],
    tierNote: opportunity.tierNote,
    ctaLabel: opportunity.ctaLabel,
    userValueScore: opportunity.userValueScore,
    applyUrl: opportunity.applyUrl,
    verifiedAt: opportunity.verifiedAt,
  });
}

export function toPublicOpportunityDetail(opportunity: PublicOpportunity): PublicOpportunityDetail {
  return Object.freeze({
    card: toPublicOpportunityCard(opportunity),
    participationMethod: opportunity.participationMethod,
    payer: opportunity.payer,
    qualifications: opportunity.qualifications,
    sourceUrl: opportunity.sourceUrl,
    status: opportunity.status,
    monetizationRole: opportunity.monetizationRole,
  });
}
