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
  IMMEDIATE: '지금 바로 참여 시작',
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
